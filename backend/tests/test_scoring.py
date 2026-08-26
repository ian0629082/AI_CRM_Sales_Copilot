"""Lead Scoring 的單元測試。

這些測試沒有資料庫、沒有 HTTP、沒有 mock —— 因為 calculate_score 是純函式。
這正是把它寫成純函式的回報：一個規則引擎如果難測，通常代表它被綁在
不該綁的東西上（例如直接讀資料庫）。

測試的重點不是「65 分對不對」，而是**規則之間的相對關係**：
說不急要輸給沒講、概數預算要輸給精確預算。
分數的絕對值日後可能會調，但這些關係一旦反了，排序就是錯的。
"""

import pytest

from app.models.enums import LeadLevel, PropertyType, Purpose, Urgency
from app.models.lead import Lead
from app.services.scoring_service import (
    HOT_THRESHOLD,
    WARM_THRESHOLD,
    ScoreResult,
    calculate_score,
    level_for_score,
)

PREFIX = "/api/v1"


def make_lead(**fields) -> Lead:
    """建一個什麼都沒填的 Lead，再蓋上想測的欄位。

    直接 new 一個 model 物件而不進資料庫 —— 計分不需要資料庫。
    """
    defaults = {
        "name": "測試客戶",
        "phone": None,
        "location": None,
        "budget_min": None,
        "budget_max": None,
        "budget_is_approximate": False,
        "rooms": None,
        "property_type": None,
        "purpose": None,
        "purchase_timeline": None,
        "urgency": None,
    }
    return Lead(**{**defaults, **fields})


def score_of(lead: Lead) -> int:
    return calculate_score(lead).score


def codes_of(result: ScoreResult) -> set[str]:
    return {r.code for r in result.reasons}


# ---------------------------------------------------------------- 決定性


def test_same_input_always_gives_same_score():
    """相同資料永遠得到相同分數 —— 這是整套 Scoring 的賣點。

    LLM 做不到這件事，所以計分才堅持用規則引擎。
    """
    lead = make_lead(location="七期", budget_max=20000000, rooms=3, phone="0912345678")

    assert len({score_of(lead) for _ in range(20)}) == 1


def test_empty_lead_scores_zero():
    assert score_of(make_lead()) == 0


# ---------------------------------------------------------------- 只看客戶本身


def test_a_brand_new_lead_can_reach_full_marks():
    """剛填完表單、什麼都還沒發生的客戶，也拿得到 100 分。

    這是刻意的。互動紀錄一度佔 20 分，後來拿掉，因為那對新客戶不公平 ——
    不管條件多好，那幾分他都是結構性拿不到的，
    而「拿不到滿分的族群」跟「拿得到的族群」放在一起排序是危險的。

    現在這種客戶（需求清楚、留了電話、很急）會排在最前面 ——
    正是業務最該立刻打電話的那種人。
    """
    fresh = make_lead(
        phone="0912345678",
        location="七期",
        budget_max=20000000,
        rooms=3,
        property_type=PropertyType.ELEVATOR_BUILDING,
        purpose=Purpose.SELF_USE,
        purchase_timeline=2,
    )
    result = calculate_score(fresh)

    assert result.score == 100
    assert result.level is LeadLevel.HOT


# ---------------------------------------------------------------- 預算


def test_exact_budget_beats_approximate_budget():
    """「就是 2000 萬」要贏過「2000 萬左右」。

    這就是 Sprint 3 特地建立 budget_is_approximate 欄位的理由 ——
    說概數的客戶通常還在觀望，購買意願跟講得出精確數字的人有差。
    若兩者同分，那個欄位等於白建。
    """
    exact = make_lead(budget_max=20000000, budget_is_approximate=False)
    approximate = make_lead(budget_max=20000000, budget_is_approximate=True)

    assert score_of(exact) > score_of(approximate)


def test_budget_scores_once_even_with_both_bounds():
    """講出區間不該比只講上限拿更多分 —— 那是同一項資訊。"""
    single = make_lead(budget_max=20000000)
    ranged = make_lead(budget_min=15000000, budget_max=20000000)

    assert score_of(single) == score_of(ranged)


# ---------------------------------------------------------------- 購買時機


def test_urgency_high_counts_even_without_a_month_number():
    """這是 urgency 這個欄位存在的全部理由。

    「我下個月要過去上班，所以有點急」—— 有明確的時間壓力，
    卻沒有任何可以填進 purchase_timeline 的月數。
    只看月數的話，這種客戶會被當成沒有急迫性。
    """
    urgent = make_lead(urgency=Urgency.HIGH)

    assert score_of(urgent) > 0
    assert "timing_urgent" in codes_of(calculate_score(urgent))


def test_saying_not_urgent_scores_lower_than_saying_nothing():
    """「客戶說不急」要輸給「客戶沒講」。

    LOW 是資訊，null 是沒有資訊。沒講的那位說不定其實很急，
    已知的冷客戶就該排在未知客戶的後面。

    若兩者同分，urgency 這個欄位在計分上就白加了。
    """
    silent = make_lead(location="七期", budget_max=20000000, rooms=3)
    cold = make_lead(
        location="七期", budget_max=20000000, rooms=3, urgency=Urgency.LOW
    )

    assert score_of(cold) < score_of(silent)


def test_over_a_year_is_treated_as_cold():
    """超過一年跟「說不急」同等看待。

    一年半、兩年，在業務動作上沒有差別，都是往後排，
    所以不必為了區分它們去雕琢月數的抽取準確度。
    """
    assert "timing_cold" in codes_of(calculate_score(make_lead(purchase_timeline=18)))


def test_month_number_and_urgency_do_not_double_count():
    """既講了「三個月內」又講了「有點急」，只算一次急迫加分。

    重複加分會讓話多的客戶莫名其妙變高分。
    """
    both = make_lead(purchase_timeline=3, urgency=Urgency.HIGH)
    only_months = make_lead(purchase_timeline=3)

    assert score_of(both) == score_of(only_months)


def test_mid_term_scores_between_urgent_and_silent():
    urgent = score_of(make_lead(purchase_timeline=2))
    mid = score_of(make_lead(purchase_timeline=8))
    silent = score_of(make_lead())

    assert urgent > mid > silent


def test_score_never_goes_below_zero():
    """扣分不能把分數壓成負的。

    負分讓畫面難讀，而且排序上跟 0 分沒有差別 —— 沒有好處。
    """
    assert score_of(make_lead(urgency=Urgency.LOW)) == 0


# ---------------------------------------------------------------- 分級與理由


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (100, LeadLevel.HOT),
        (HOT_THRESHOLD, LeadLevel.HOT),  # 門檻上剛好那一分算高的那一級
        (HOT_THRESHOLD - 1, LeadLevel.WARM),
        (WARM_THRESHOLD, LeadLevel.WARM),
        (WARM_THRESHOLD - 1, LeadLevel.COLD),
        (0, LeadLevel.COLD),
    ],
)
def test_level_thresholds_are_inclusive(score, expected):
    """門檻上剛好那一分算高的那一級，不是低的。

    邊界值最容易寫反（>= 寫成 >），而且寫反了畫面上看不出來 ——
    只是有些客戶莫名其妙少一級。
    """
    assert level_for_score(score) is expected


def test_reasons_add_up_to_the_score():
    """理由清單的加總必須等於分數。

    這是「可解釋」的字面意思：業務看到的每一條理由，
    加起來要剛好是他看到的那個分數。對不起來就代表有一條規則沒被列出來。
    """
    lead = make_lead(
        phone="0912345678",
        location="七期",
        budget_max=20000000,
        budget_is_approximate=True,
        rooms=3,
        purpose=Purpose.INVESTMENT,
        purchase_timeline=2,
    )
    result = calculate_score(lead)

    assert sum(r.points for r in result.reasons) == result.score


def test_reasons_are_empty_for_an_empty_lead():
    result = calculate_score(make_lead())

    assert result.reasons == []
    assert result.level is LeadLevel.COLD


# ---------------------------------------------------------------- 真的接上了嗎
#
# 上面測的是規則本身。這一段測的是「規則有沒有真的被呼叫到」——
# 一個算得完全正確、但沒人呼叫的計分引擎，跟沒寫是一樣的。


def test_score_is_calculated_on_create(client):
    resp = client.post(
        f"{PREFIX}/leads",
        json={
            "name": "王先生",
            "phone": "0912345678",
            "location": "七期",
            "budget_max": 20000000,
            "rooms": 3,
            "purpose": "SELF_USE",
            "purchase_timeline": 2,
        },
    )

    # 剛建檔、什麼互動都還沒有的客戶就能拿到滿分 —— 這是刻意的
    assert resp.json()["lead_score"] == 100


def test_score_updates_when_requirements_change(client):
    lead = client.post(f"{PREFIX}/leads", json={"name": "王先生"}).json()

    after = client.patch(
        f"{PREFIX}/leads/{lead['id']}",
        json={"location": "七期", "budget_max": 20000000},
    ).json()

    assert after["lead_score"] > lead["lead_score"]


def test_interactions_do_not_change_the_score(client):
    """互動不影響 Lead Score —— 這是「分數只看客戶本身」的直接後果。

    「跟進到哪一步」由 Need Follow-up 回答，兩件事分開算。
    """
    lead = client.post(
        f"{PREFIX}/leads", json={"name": "王先生", "location": "七期"}
    ).json()

    client.post(
        f"{PREFIX}/leads/{lead['id']}/interactions",
        json={"type": "VIEWING", "content": "帶看兩間"},
    )
    after = client.get(f"{PREFIX}/leads/{lead['id']}").json()

    assert after["lead_score"] == lead["lead_score"]


def test_detail_page_explains_the_score(client):
    """業務看得到分數是怎麼來的，而且理由加起來要等於分數。"""
    lead = client.post(
        f"{PREFIX}/leads",
        json={
            "name": "王先生",
            "phone": "0912345678",
            "location": "七期",
            "budget_max": 20000000,
        },
    ).json()

    detail = client.get(f"{PREFIX}/leads/{lead['id']}").json()

    codes = {r["code"] for r in detail["score_reasons"]}
    assert {"phone", "location", "budget_exact"} <= codes
    assert sum(r["points"] for r in detail["score_reasons"]) == detail["lead_score"]
