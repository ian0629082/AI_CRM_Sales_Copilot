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
    check_uses_history,
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


def test_chinese_numerals_are_ignored():
    """中文數字不抓。

    「三天後再打給他」的「三」是模型自己算出來的時間，不是引用客戶的話。
    抓了只會製造一堆假警報，而一個天天誤報的指標會被忽略，
    然後真的出事時也沒人看。
    """
    assert check_numbers_grounded("三天後再約他看屋", SOURCE).verdict is Verdict.PASS


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
