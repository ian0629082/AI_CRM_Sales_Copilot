"""跟進建議評估判準的單元測試。

**評估程式本身也會寫錯**，而一份算錯的數字比沒有數字更糟 ——
它會讓人對著錯的方向調 prompt，而且錯得很難察覺：
沒有人會懷疑「捏造率 0%」是算錯的。

這份測試跟 test_evaluation_metrics.py 是同一個理由存在的。
"""

import pytest

from evaluation.followup_criteria import (
    FollowUpReport,
    Verdict,
    check_actionable,
    check_grounding,
    check_numbers_grounded,
    check_timing_matches_appointment,
    check_uses_history,
    check_viewing_confirmed,
    evaluate_case,
)

SOURCE = "想在七期找三房，我下個月要過去上班所以有點急\n客戶說週末想看那間，預算 2000 萬"
INTERACTIONS = "客戶說週末想看那間，預算 2000 萬"


# ---------------------------------------------------------------- grounding


def test_verbatim_quote_passes():
    assert check_grounding(["下個月要過去上班"], SOURCE).verdict is Verdict.PASS


def test_paraphrase_fails():
    """改寫過的引用一律判失敗。

    「下個月要去上班」跟原話只差一個字，意思完全一樣，這裡仍然判失敗。
    一旦允許「意思差不多」，這條判準就從逐字比對滑成語意判斷 ——
    而語意判斷需要另一個模型，那正是我們想避免的。
    """
    assert check_grounding(["下個月要去上班"], SOURCE).verdict is Verdict.FAIL


def test_whitespace_only_difference_passes():
    assert check_grounding(["下個月 要過去上班"], SOURCE).verdict is Verdict.PASS


def test_empty_evidence_passes():
    """沒有引用任何東西不算捏造。

    第一次聯絡的新客戶，本來就沒有什麼可以引用的。
    把它判失敗會逼著模型硬掰一句話出來，那才是真的災難。
    """
    assert check_grounding([], SOURCE).verdict is Verdict.PASS


def test_one_bad_quote_fails_the_whole_case():
    """只要有一條沒出處，這一筆就算失敗，不看比例。

    捏造不能用「其他三條都對」來抵銷 —— 業務照著念出去的可能就是那一句。
    """
    result = check_grounding(["下個月要過去上班", "他說預算可以到三千萬"], SOURCE)
    assert result.verdict is Verdict.FAIL
    assert "1 條" in result.detail


def test_blank_quote_counts_as_ungrounded():
    """空字串不能算通過 —— 空字串是任何字串的子字串。"""
    assert check_grounding([" "], SOURCE).verdict is Verdict.FAIL


# ---------------------------------------------------------------- uses_history


def test_quote_from_interactions_passes():
    assert check_uses_history(["週末想看那間"], INTERACTIONS).verdict is Verdict.PASS


def test_quote_only_from_raw_requirement_fails():
    """有互動紀錄卻只引用客戶原話，代表建議沒有用到歷史。"""
    assert check_uses_history(["下個月要過去上班"], INTERACTIONS).verdict is Verdict.FAIL


def test_no_interactions_is_not_applicable():
    """沒有互動紀錄時回 N/A，不是失敗。

    第一次聯絡本來就沒有歷史可以引用，判它失敗會讓這個指標無法解讀。
    """
    assert check_uses_history([], "").verdict is Verdict.NOT_APPLICABLE


# ---------------------------------------------------------------- actionable


@pytest.mark.parametrize("action", ["持續追蹤", "保持聯繫", "再聯絡看看"])
def test_empty_phrases_fail(action):
    assert check_actionable(action).verdict is Verdict.FAIL


def test_specific_action_passes():
    assert check_actionable("致電確認上週看的物件他考慮得如何").verdict is Verdict.PASS


def test_empty_phrase_with_real_content_passes():
    """「持續追蹤他對三房的想法」講了具體的事，不該因為前四個字被判死。"""
    assert check_actionable("持續追蹤他對三房預算的想法").verdict is Verdict.PASS


def test_too_short_fails():
    assert check_actionable("打電話").verdict is Verdict.FAIL


# ---------------------------------------------------------------- numbers


def test_number_from_source_passes():
    assert check_numbers_grounded("預算 2000 萬那間", SOURCE).verdict is Verdict.PASS


def test_invented_number_fails():
    result = check_numbers_grounded("那間開價 3500 萬", SOURCE)
    assert result.verdict is Verdict.FAIL
    assert "3500" in result.detail


def test_numbers_without_a_property_unit_are_ignored():
    """「花 1 分鐘跟您確認」不是捏造。

    第一輪評估真的誤判了這一筆。那個 1 客戶確實沒講過，
    但它是業務自己的話，不是關於客戶的事實。
    這條判準要抓的是坪數、價格、樓層、屋齡——業務會照著念、
    念錯了客戶當場就知道他在編的那種數字。
    """
    assert check_numbers_grounded("我先花 1 分鐘跟您確認", SOURCE).verdict is Verdict.PASS


def test_property_unit_numbers_are_still_caught():
    for text in ("那間 35 坪", "在 12 樓", "屋齡 8 年"):
        assert check_numbers_grounded(text, SOURCE).verdict is Verdict.FAIL


def test_chinese_numerals_are_ignored():
    """中文數字不抓。

    「三天後再打給他」的「三」是模型自己算出來的時間，不是引用客戶的話。
    抓了只會製造一堆假警報，而一個天天誤報的指標會被忽略，
    然後真的出事時也沒人看。
    """
    assert check_numbers_grounded("三天後再約他看屋", SOURCE).verdict is Verdict.PASS


# ---------------------------------------------------------------- 時機


APPOINTMENT = "客戶說這週要跟先生討論，叫我下週三下午再打給她"


def test_timing_must_match_the_day_the_customer_named():
    """客戶約下週三，建議今天下午——這是這條判準唯一要抓的東西。

    注意「今天下午」跟「下週三下午」都含「下午」。
    如果比對只看時段，這一筆會被判成通過，那這條判準就白寫了。
    """
    result = check_timing_matches_appointment("今天下午", APPOINTMENT)
    assert result.verdict is Verdict.FAIL
    assert "下週三" in result.detail


def test_timing_matching_the_appointment_passes():
    assert (
        check_timing_matches_appointment("下週三下午", APPOINTMENT).verdict is Verdict.PASS
    )


def test_no_appointment_is_not_applicable():
    """客戶沒約時間，業務自己決定何時打，這條判準不適用。"""
    assert (
        check_timing_matches_appointment("明天上午", SOURCE).verdict
        is Verdict.NOT_APPLICABLE
    )


def test_availability_about_viewing_is_not_an_appointment():
    """「約週末看屋，她只有週六下午有空」——那是看屋時間，不是回電時間。

    業務要打電話確認一件事，不必等到客戶有空看房。
    """
    source = "約週末看屋，客戶說她只有週六下午有空"
    result = check_timing_matches_appointment("今天下班前", source)
    assert result.verdict is Verdict.NOT_APPLICABLE
    assert "看屋" in result.detail


def test_availability_about_contact_is_an_appointment():
    """同一句「有空」，講的是電話就要照做。

    這是業務實務判斷：「我只有週六下午有空」可能是「你週六下午再打給我」，
    也可能是「我週六下午才能去看房子」，意思完全相反。
    所以要看前後文在講聯絡還是看屋，不能一律當成其中一種。
    """
    source = "客戶說他平日都在忙，電話的話只有週六下午有空"
    assert (
        check_timing_matches_appointment("今天下班前", source).verdict is Verdict.FAIL
    )
    assert (
        check_timing_matches_appointment("週六下午", source).verdict is Verdict.PASS
    )


def test_ambiguous_availability_does_not_fail():
    """看不出來在講什麼就不判失敗。

    這條判準寧可漏抓，也不要誤殺一則其實正常的建議——
    一個會誤報的指標，業務看兩次就不看了。
    """
    source = "客戶說他只有週六下午有空"
    assert (
        check_timing_matches_appointment("今天下班前", source).verdict
        is Verdict.NOT_APPLICABLE
    )


def test_vague_promise_is_not_applicable():
    """「有物件再通知我」不是約時間，是把決定權交給業務。"""
    assert (
        check_timing_matches_appointment("這週五", "客戶說有物件再通知我").verdict
        is Verdict.NOT_APPLICABLE
    )


# ------------------------------------------------- 業務自己打的字，不是客戶的原話
#
# 這一組是專案作者（具房仲實務經驗）指出來的：
# 互動紀錄是業務事後轉述，不會出現「你下週三再打給我」那種第一人稱句子。
# 第一版的規則只認得客戶的口吻，於是這條判準的**分母被壓到接近零** ——
# holdout 5 筆全部不適用、開發集 14 筆也只有 1 筆適用。
#
# 沒有分母的通過率是憑空的，而它看起來有數字，所以比缺數字更危險。


@pytest.mark.parametrize(
    "record",
    [
        "客戶請我下週三聯繫",
        "客戶說下週三再聯絡他",
        "約下週三回電",
        "客戶下週三才有空，約好那天再談",
        "客戶要我下週再找他",
        "說再等等，下週三我再打",
    ],
)
def test_salesperson_phrasing_counts_as_an_appointment(record: str):
    """業務轉述的寫法也要認得，否則這條判準等於沒有在跑。"""
    assert check_timing_matches_appointment("今天下午", record).verdict is Verdict.FAIL
    assert check_timing_matches_appointment("下週三", record).verdict is Verdict.PASS


@pytest.mark.parametrize("written", ["下周二", "下週二", "下星期二"])
@pytest.mark.parametrize("answered", ["下周二", "下週二", "下星期二"])
def test_week_day_spellings_are_interchangeable(written: str, answered: str):
    """「下周二」「下週二」「下星期二」是同一天，九種組合都要對得上。

    不收斂寫法的話會出兩種錯，而且方向相反：
    業務寫「下周二」時間詞抓不到，這筆就從分母裡消失；
    抓到了但模型答「下週二」，又會因為字面不同被誤判成失敗 ——
    而模型其實完全答對了。後者更糟，一個會誤報的指標沒有人會看。
    """
    record = f"客戶請我{written}再聯繫"
    assert check_timing_matches_appointment(answered, record).verdict is Verdict.PASS


@pytest.mark.parametrize("written", ["下周二", "下星期二"])
def test_week_day_spellings_still_catch_a_wrong_day(written: str):
    """收斂寫法不能連「答錯天」都一起放過。"""
    record = f"客戶請我{written}再聯繫"
    assert check_timing_matches_appointment("今天下午", record).verdict is Verdict.FAIL


def test_promised_answer_counts_as_an_appointment():
    """「客戶說他哪天給我答覆」算約定 —— 這是實務判斷。

    客戶說了哪天給答案，那天業務就該主動打過去，
    不能真的坐在那邊等他來電。
    """
    record = "客戶說他考慮一下，週五前給我答覆"
    assert check_timing_matches_appointment("今天下午", record).verdict is Verdict.FAIL
    assert check_timing_matches_appointment("週五", record).verdict is Verdict.PASS


@pytest.mark.parametrize(
    ("record", "why"),
    [
        ("已聯繫上，詢問需求後，有適合案件會再與客戶連絡", "有案子才聯絡，不是約時間"),
        ("約好8/29號要到公司與屋主碰面喬價格", "碰面談價是見面約，不是回電約"),
        ("傳了三間的資料給他，約好明天下午15:00帶看", "帶看約，前一天本來就該先確認"),
        ("帶看完後表示比較喜歡三房的，回去評估一下", "根本沒有約下次"),
        ("打電話追蹤，客戶沒接", "業務自己的動作，不是客戶的約定"),
    ],
)
def test_salesperson_notes_that_are_not_callback_promises(record: str, why: str):
    """放寬的是「有多少案例被檢查」，不是「什麼樣的建議算通過」。

    這一組守的就是那條界線：擴充說法清單之後，
    這些原本就不該被檢查的紀錄仍然不會被拉進來誤殺。
    """
    assert (
        check_timing_matches_appointment("今天下午", record).verdict
        is Verdict.NOT_APPLICABLE
    ), why


# ---------------------------------------------------------------- 彙總


def _case(case_id: str, **suggestion):
    payload = {
        "next_action": "致電確認上週看的物件他考慮得如何",
        "talking_point": "陳先生您好，上次您提到下個月要過去上班⋯⋯",
        "suggested_timing": "明天上午",
        "evidence": ["下個月要過去上班"],
    }
    payload.update(suggestion)
    return evaluate_case(
        case_id=case_id,
        tags=[],
        suggestion=payload,
        source_text=SOURCE,
        interaction_text=INTERACTIONS,
    )


def test_pass_rate_excludes_not_applicable():
    """通過率的分母不含 N/A。

    這是這個檔案裡最重要的一個測試。把 N/A 算成通過的話，
    「有用到互動歷史」這條在一份全是新客戶的資料集上會顯示 100%，
    而它實際上一次都沒被考過 —— 那個 100% 會直接被寫進報告。
    """
    with_history = _case("a", evidence=["週末想看那間"])
    without_history = evaluate_case(
        case_id="b",
        tags=[],
        suggestion={
            "next_action": "致電了解他目前的需求與時間",
            "talking_point": "您好",
            "suggested_timing": "今天下午",
            "evidence": [],
        },
        source_text=SOURCE,
        interaction_text="",
    )

    report = FollowUpReport(model="m", prompt_version="v", cases=[with_history, without_history])
    stats = report.per_criterion["uses_history"]

    assert stats.passed == 1
    assert stats.not_applicable == 1
    assert stats.pass_rate == 1.0  # 分母是 1 而不是 2


def test_clean_rate_needs_every_criterion():
    """四條裡有一條失敗，這一則就不算乾淨。

    業務拿到的是一整則建議，不是四條分開的指標。
    """
    good = _case("a", evidence=["週末想看那間"])
    bad = _case("b", next_action="持續追蹤", evidence=["週末想看那間"])

    report = FollowUpReport(model="m", prompt_version="v", cases=[good, bad])

    assert good.is_clean
    assert not bad.is_clean
    assert report.clean_rate == 0.5


def test_criteria_are_not_weighted_into_one_score():
    """判準是四個獨立的數字，不合成總分。

    合成總分會讓「捏造」被「語氣不錯」補回來，而捏造是不能被補的。
    這個測試守的是 Report 上沒有那種 API —— 有人加了它就會紅。
    """
    report = FollowUpReport(model="m", prompt_version="v", cases=[_case("a")])

    assert not hasattr(report, "overall_score")
    assert set(report.per_criterion) >= {
        "grounding",
        "uses_history",
        "actionable",
        "numbers_grounded",
    }


# ---------------------------------------------------------------- 帶看確認


def test_viewing_confirmation_is_required_the_day_before():
    """明天要帶看，建議卻在講別的——這條要抓的就是這個。"""
    result = check_viewing_confirmed(
        "致電了解他對林口的看法", "何小姐，想跟您聊聊林口那邊的行情⋯⋯", True
    )
    assert result.verdict is Verdict.FAIL


def test_confirming_the_viewing_passes():
    result = check_viewing_confirmed(
        "致電確認明天帶看的時間", "郭先生，跟您確認一下明天下午三點看屋還方便嗎？", True
    )
    assert result.verdict is Verdict.PASS


def test_no_viewing_tomorrow_is_not_applicable():
    """這條判準只在帶看前一天有意義，其他日子不適用。"""
    result = check_viewing_confirmed("致電了解他的需求", "您好⋯⋯", False)
    assert result.verdict is Verdict.NOT_APPLICABLE


def test_wrapping_quotes_are_not_fabrication():
    """模型自己加的一對引號不算捏造。

    這條是**在看過 holdout 的失敗之後才加的**，所以要講清楚它為什麼
    不是「數字不好看就放寬標準」：

    判斷的標準只有一條 —— 改完之後會不會放過真正的捏造？
    不會。拿掉的只有最外層引號，內容仍然必須逐字相符。
    """
    assert check_grounding(["「下個月要過去上班」"], SOURCE).verdict is Verdict.PASS


def test_only_the_outermost_quotes_are_stripped():
    """句子中間的引號是內容的一部分，不能拿掉。

    客戶說「他跟我說『再看看』」，那個『再看看』是他真的講過的字。
    連中間的引號都脫掉的話，這條判準就會開始放過改寫過的句子。
    """
    source = "客戶說他跟我說『再看看』就掛了"
    assert check_grounding(["他跟我說『再看看』"], source).verdict is Verdict.PASS
    assert check_grounding(["他跟我說再看看"], source).verdict is Verdict.FAIL
