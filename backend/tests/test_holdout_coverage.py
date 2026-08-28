"""判準覆蓋率腳本的測試。

為什麼這支輔助腳本也要測：它的輸出會決定「還要不要繼續補題」。
算錯的話，後果是拿一份其實沒考到那條判準的資料集去宣稱通過率 ——
而那種錯誤沒有人會察覺，因為報告上就是有一個數字。

這跟評估程式本身要有測試是同一條理由（見 docs/PROGRESS.md）。
"""

from datetime import date

from scripts.holdout_coverage import ALWAYS_APPLICABLE, applicability

TODAY = date(2026, 8, 27)


def make_case(**overrides) -> dict:
    """一筆最陽春的情境：有原話、沒有互動紀錄、沒有帶看、沒有回電約定。"""
    case = {
        "id": "t-001",
        "days_since_created": 3,
        "lead": {"name": "測試客戶", "raw_requirement": "我想找大里的透天，預算 1500 萬"},
        "interactions": [],
    }
    case.update(overrides)
    return case


def test_always_applicable_criteria_are_always_counted():
    """這三條的適用性由模型輸出決定，但它們永遠適用，不會有 N/A。"""
    flags = applicability(make_case(), TODAY)
    for name in ALWAYS_APPLICABLE:
        assert flags[name] is True


def test_uses_history_needs_interactions():
    """沒有互動紀錄的客戶，不能要求建議引用互動紀錄。"""
    assert applicability(make_case(), TODAY)["uses_history"] is False

    with_history = make_case(
        interactions=[{"days_ago": 2, "type": "CALL", "content": "客戶說他還在考慮"}]
    )
    assert applicability(with_history, TODAY)["uses_history"] is True


def test_timing_needs_an_explicit_callback_promise():
    """「時機對得上」只在客戶自己約了回電時間時才有意義。

    這正是原本 5 筆 holdout 一次都沒考到的那一條 ——
    它不是通過率低，是**分母是零**，數字憑空而來。
    """
    assert applicability(make_case(), TODAY)["timing_matches"] is False

    promised = make_case(
        interactions=[
            {"days_ago": 1, "type": "CALL", "content": "客戶說下週三再打給他"}
        ]
    )
    assert applicability(promised, TODAY)["timing_matches"] is True


def test_viewing_appointment_only_counts_the_day_before():
    """帶看確認這條判準只在帶看前一天有意義。"""
    tomorrow = make_case(viewing_in_days=1, viewing_hour=15)
    assert applicability(tomorrow, TODAY)["viewing_confirmed"] is True

    next_week = make_case(viewing_in_days=7, viewing_hour=15)
    assert applicability(next_week, TODAY)["viewing_confirmed"] is False


def test_viewing_talk_is_not_mistaken_for_a_callback_promise():
    """客戶講的是「什麼時候方便看房」，不是「什麼時候打給我」。

    兩者對業務的意義相反：後者要照做，前者不必等 ——
    帶看前一天本來就該先打電話確認。
    """
    viewing_talk = make_case(
        interactions=[
            {"days_ago": 1, "type": "LINE", "content": "她說週六下午有空可以去看屋"}
        ]
    )
    assert applicability(viewing_talk, TODAY)["timing_matches"] is False
