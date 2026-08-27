"""手填表格 → JSON 的轉檔測試。

這支程式錯了，整份驗證集就是錯的，而且錯得很難察覺：
它照樣產得出檔案、評估照樣跑得完、報告照樣有數字。

跟 test_evaluation_metrics.py、test_followup_criteria.py 是同一個理由存在的。
"""

from datetime import date

import pytest

from scripts.build_holdout import (
    FormError,
    parse_block,
    parse_date,
    parse_days_ago,
    parse_interaction,
    parse_money,
    parse_viewing,
    split_blocks,
)

ANCHOR = date(2026, 8, 27)

FILLED = """
=== 第 1 位 ===

姓名：陳先生
電話：0912345678
狀態：有興趣
建檔日期：8/7

客戶原話：想在竹北找三房，預算抓一千八，小孩明年要念國小

區域：竹北
預算：1800萬
房數：3
房屋類型：電梯大樓
屋齡上限：15 年
車位：要
目的：自住
急迫：急

下次提醒：8/24
已約帶看：8/28 15:00

互動紀錄（最新的寫最上面，一行一筆，沒有就整段留空）
8/25 電話 跟他約好禮拜四下午看光明六路那間
8/21 LINE 傳了兩間竹北的資料給他
--- 這一位結束 ---
"""


def _parse_first(text: str):
    title, lines = split_blocks(text)[0]
    return parse_block(title, lines, 1, ANCHOR)


def test_a_filled_block_becomes_a_case():
    case = _parse_first(FILLED)

    assert case["id"] == "hold-001"
    assert case["days_since_created"] == 20  # 8/7 到 8/27
    assert case["next_follow_up_in_days"] == -3
    assert case["viewing_in_days"] == 1
    assert case["viewing_hour"] == 15

    lead = case["lead"]
    assert lead["name"] == "陳先生"
    assert lead["status"] == "INTERESTED"
    assert lead["budget_max"] == 18_000_000
    assert lead["property_type"] == "ELEVATOR_BUILDING"
    assert lead["building_age_max"] == 15
    assert lead["parking"] is True
    assert lead["purpose"] == "SELF_USE"
    assert lead["urgency"] == "HIGH"

    assert [i["type"] for i in case["interactions"]] == ["CALL", "LINE"]
    assert case["interactions"][0]["days_ago"] == 2


def test_untouched_blocks_are_skipped():
    """表格裡沒用到的空位直接跳過，不是錯誤。

    給了 15 個空位、只填 12 位是很正常的事，
    為了這個逼人去刪掉三段文字沒有道理。
    """
    blank = """
=== 第 1 位 ===

姓名：
電話：
狀態：
建檔幾天了：

互動紀錄（最新的寫最上面，一行一筆，沒有就整段留空）
--- 這一位結束 ---
"""
    assert _parse_first(blank) is None


def test_filling_everything_but_the_name_is_an_error():
    """填了一半卻沒填姓名，多半是漏了，不能安靜地跳過。

    安靜跳過的話，他以為自己出了 15 題，實際上只跑了 14 題，
    而報告上的分母不會告訴他這件事。
    """
    half = """
=== 第 2 位 ===

姓名：
狀態：有興趣
建檔幾天了：10
--- 這一位結束 ---
"""
    with pytest.raises(FormError, match="姓名"):
        _parse_first(half)


def test_empty_fields_are_left_out_entirely():
    """沒填的欄位不會變成 null，而是整個不存在。"""
    minimal = """
=== 第 1 位 ===

姓名：王小姐
狀態：新進
建檔幾天了：2
--- 這一位結束 ---
"""
    lead = _parse_first(minimal)["lead"]
    assert set(lead) == {"name", "status"}


# ---------------------------------------------------------------- 預算


@pytest.mark.parametrize(
    "text,expected",
    [
        ("1500萬", (None, 15_000_000)),
        ("1500 萬", (None, 15_000_000)),
        ("15000000", (None, 15_000_000)),
        ("1.2億", (None, 120_000_000)),
        ("1200萬到1500萬", (12_000_000, 15_000_000)),
        ("1200萬~1500萬", (12_000_000, 15_000_000)),
        ("", (None, None)),
    ],
)
def test_money_in_everyday_wording(text, expected):
    """填表的人腦子裡想的是「一千五百萬」，不是 15000000。

    逼他自己換算，就是多一個填錯的機會 —— 而多打一個零，
    這筆客戶的分數與 AI 的建議會全部跟著錯。
    """
    assert parse_money(text) == expected


def test_backwards_budget_range_is_caught():
    with pytest.raises(FormError, match="下限比上限大"):
        parse_money("1500萬到1200萬")


def test_unreadable_budget_is_caught():
    with pytest.raises(FormError, match="預算看不懂"):
        parse_money("看情況")


# ---------------------------------------------------------------- 其他格式


def test_interaction_line():
    item = parse_interaction("3天前 電話 客戶說他還在考慮，叫我下週再打給他", ANCHOR)
    assert item == {
        "type": "CALL",
        "days_ago": 3,
        "content": "客戶說他還在考慮，叫我下週再打給他",
    }


def test_interaction_line_missing_content_is_caught():
    """漏了內容要當場講清楚該怎麼寫，不要只說「格式錯誤」。"""
    with pytest.raises(FormError, match="看不懂"):
        parse_interaction("3天前 電話", ANCHOR)


def test_viewing_needs_both_day_and_hour():
    assert parse_viewing("1 15", ANCHOR) == (1, 15)
    with pytest.raises(FormError, match="看不懂"):
        parse_viewing("明天", ANCHOR)


def test_viewing_hour_must_be_a_real_hour():
    with pytest.raises(FormError, match="0～23"):
        parse_viewing("1 35", ANCHOR)


def test_decorative_separators_do_not_start_a_block():
    """範本開頭那條 ====== 分隔線不是一位客戶。

    這個真的踩到過：說明文字被當成某一位的欄位，
    然後程式報出一堆看不懂的錯，而表格其實一個字都還沒填。
    對一個第一次填表的人來說，那種錯誤訊息足以讓他直接放棄。
    """
    text = """
================================================================
互動紀錄照你平常真的會打的字寫。
================================================================

=== 第 1 位 ===
姓名：陳先生
狀態：新進
建檔幾天了：2
--- 這一位結束 ---
"""
    blocks = split_blocks(text)
    assert [title for title, _ in blocks] == ["第 1 位"]


def test_bracketed_hint_lines_are_skipped():
    """範本裡用括號包起來的範例行，刪不刪都不影響結果。"""
    text = """
=== 第 1 位 ===
姓名：林小姐
狀態：有興趣
建檔幾天了：5

互動紀錄（最新的寫最上面，一行一筆，沒有就整段留空）
（3天前 電話 這是範例，程式應該跳過）
2天前 電話 真正的紀錄
--- 這一位結束 ---
"""
    title, lines = split_blocks(text)[0]
    case = parse_block(title, lines, 1)
    assert [i["content"] for i in case["interactions"]] == ["真正的紀錄"]


def test_no_limit_wording_counts_as_blank():
    """「不限」是明確回答「客戶沒有這個要求」，不是填錯。

    逼人把「不限」改成留空，只是要他配合程式的想法。
    """
    text = """
=== 第 1 位 ===
姓名：胡小姐
狀態：已聯絡
建檔幾天了：2
房數：不限
屋齡上限：不限
--- 這一位結束 ---
"""
    title, lines = split_blocks(text)[0]
    lead = parse_block(title, lines, 1)["lead"]
    assert "rooms" not in lead
    assert "building_age_max" not in lead


def test_content_on_the_interactions_header_line_is_an_error():
    """把互動內容直接寫在「互動紀錄」那一行，不能靜默丟掉。

    這真的發生過。原本的程式把整行當標題跳過，那筆紀錄就這樣消失——
    他以為自己出了一題有互動歷史的，實際上跑的是一題沒有歷史的，
    而報告上不會有任何跡象。靜默丟資料是這支程式最不能犯的錯。
    """
    text = """
=== 第 1 位 ===
姓名：胡小姐
狀態：已聯絡
建檔幾天了：2

互動紀錄 已聯繫上，詢問需求後有適合案件會再與客戶連絡
--- 這一位結束 ---
"""
    title, lines = split_blocks(text)[0]
    with pytest.raises(FormError, match="不要直接寫內容"):
        parse_block(title, lines, 1)


# ---------------------------------------------------------------- 日期


def test_dates_are_converted_relative_to_the_anchor():
    """表格裡寫日期，程式換算成相對天數。

    業務在 CRM 裡看到的是日期，腦子裡想的也是日期。
    逼他自己換算成「幾天前」，是拿程式的方便去換他的麻煩 ——
    而且換算錯了不會有人發現。
    """
    text = """
=== 第 1 位 ===
姓名：胡小姐
狀態：已聯絡
建檔日期：8/25
下次提醒：8/30
已約帶看：8/28 15:00

互動紀錄（一行一筆）
8/26 電話 已聯繫上，問完需求
8/20 LINE 傳了兩間資料給她
--- 這一位結束 ---
"""
    title, lines = split_blocks(text)[0]
    case = parse_block(title, lines, 1, ANCHOR)

    assert case["days_since_created"] == 2
    assert case["next_follow_up_in_days"] == 3
    assert case["viewing_in_days"] == 1
    assert case["viewing_hour"] == 15
    assert [i["days_ago"] for i in case["interactions"]] == [1, 7]


def test_a_past_reminder_date_means_overdue():
    """提醒日已經過了，就是逾期 —— 不必逼人去寫負數。"""
    text = """
=== 第 1 位 ===
姓名：王先生
狀態：新進
建檔日期：8/1
下次提醒：8/22
--- 這一位結束 ---
"""
    title, lines = split_blocks(text)[0]
    assert parse_block(title, lines, 1, ANCHOR)["next_follow_up_in_days"] == -5


def test_month_day_without_year_looks_backwards():
    """一月時寫 12/28，指的是去年 —— 不是十一個月後。"""
    assert parse_date("12/28", date(2026, 1, 10), prefer_past=True) == date(2025, 12, 28)


def test_the_old_days_ago_wording_still_works():
    """舊的「3天前」寫法要繼續能用。

    表格改版不該讓已經填好的人重填 —— 那是最容易讓人直接放棄的事。
    """
    assert parse_days_ago("3天前", ANCHOR) == 3
    assert parse_days_ago("8/24", ANCHOR) == 3


def test_a_future_interaction_date_is_caught():
    """互動紀錄是已經發生的事，日期不能比基準日晚。"""
    with pytest.raises(FormError, match="比基準日還晚"):
        parse_interaction("9/5 電話 明天要打的", ANCHOR)
