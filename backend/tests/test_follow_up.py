"""Need Follow-up 的測試。

判定邏輯是純函式，而且**時間由外面傳進來**，所以測試可以自由地移動日期，
不必去 mock 系統時鐘。一個要 freeze time 才能測的規則引擎，
通常代表它偷偷去讀了 date.today()。
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.models.enums import InteractionType, LeadStatus
from app.models.interaction import Interaction
from app.models.lead import Lead
from app.services.follow_up import (
    DEFAULT_FOLLOW_UP_DAYS,
    FollowUpBucket,
    default_follow_up_days,
    evaluate,
)

PREFIX = "/api/v1"
TODAY = date(2026, 8, 26)


def make_lead(created_days_ago: int = 0, **fields) -> Lead:
    defaults = {
        "name": "測試客戶",
        "status": LeadStatus.NEW,
        "next_follow_up_at": None,
        "follow_up_muted": False,
    }
    lead = Lead(**{**defaults, **fields})
    lead.created_at = datetime.combine(
        TODAY - timedelta(days=created_days_ago),
        datetime.min.time(),
        tzinfo=timezone.utc,
    )
    return lead


def interaction() -> Interaction:
    return Interaction(type=InteractionType.CALL, content="（測試用）")


# ---------------------------------------------------------------- 新進未聯絡


def test_a_lead_created_today_is_not_chased_yet():
    """今天剛進來的客戶不用馬上跳提醒 —— 業務可能正在處理。"""
    status = evaluate(make_lead(created_days_ago=0), [], TODAY)

    assert status.bucket is FollowUpBucket.SCHEDULED
    assert not status.needs_attention


def test_an_untouched_lead_shows_up_the_next_day():
    """客戶填了表、隔天還沒人碰他，就該進清單。

    房仲實務上第一時間回應差很多，所以這個門檻刻意設得很短。
    """
    status = evaluate(make_lead(created_days_ago=1), [], TODAY)

    assert status.bucket is FollowUpBucket.NEW_UNCONTACTED
    assert status.needs_attention


def test_longer_neglect_sorts_higher():
    """晾越久的排越前面。"""
    three_days = evaluate(make_lead(created_days_ago=3), [], TODAY)
    ten_days = evaluate(make_lead(created_days_ago=10), [], TODAY)

    assert ten_days.days_overdue > three_days.days_overdue


def test_a_contacted_lead_never_lands_in_the_new_bucket():
    """只要有人聯絡過，就不再是「新進未聯絡」——
    那一堆代表的是「還沒有人認識他」，不是「很久沒動」。
    """
    lead = make_lead(created_days_ago=30, next_follow_up_at=TODAY + timedelta(days=3))

    assert evaluate(lead, [interaction()], TODAY).bucket is FollowUpBucket.SCHEDULED


# ---------------------------------------------------------------- 到期跟進


def test_due_today_counts_as_due():
    lead = make_lead(next_follow_up_at=TODAY)
    status = evaluate(lead, [interaction()], TODAY)

    assert status.bucket is FollowUpBucket.DUE
    assert status.days_overdue == 0


def test_not_due_yet_is_left_alone():
    lead = make_lead(next_follow_up_at=TODAY + timedelta(days=1))

    assert evaluate(lead, [interaction()], TODAY).bucket is FollowUpBucket.SCHEDULED


def test_overdue_days_are_counted_for_sorting():
    lead = make_lead(next_follow_up_at=TODAY - timedelta(days=5))

    assert evaluate(lead, [interaction()], TODAY).days_overdue == 5


def test_a_contacted_lead_without_a_reminder_still_gets_chased():
    """聯絡過卻沒有提醒日的，往「提醒」的方向倒。

    這種狀態代表資料不完整（多半是舊資料）。
    寧可多提醒一次，也不要讓一個客戶安靜地消失 ——
    後者沒有任何人會發現。
    """
    lead = make_lead(next_follow_up_at=None)

    assert evaluate(lead, [interaction()], TODAY).bucket is FollowUpBucket.DUE


# ---------------------------------------------------------------- 靜音與結案


def test_muted_leads_never_appear_in_any_chase_list():
    """業務說了「不用提醒」，系統就不該再有意見。

    一份會冒出你關過的人的待辦清單，沒有人敢信 ——
    而一份沒人敢信的清單，等於沒有清單。
    """
    lead = make_lead(
        created_days_ago=90,
        follow_up_muted=True,
        next_follow_up_at=TODAY - timedelta(days=30),
    )
    status = evaluate(lead, [interaction()], TODAY)

    assert status.bucket is FollowUpBucket.MUTED
    assert not status.needs_attention


def test_muting_beats_being_overdue():
    """靜音的判斷排在逾期之前，順序反了就會漏掉這個保護。"""
    lead = make_lead(created_days_ago=90, follow_up_muted=True)

    assert evaluate(lead, [], TODAY).bucket is FollowUpBucket.MUTED


@pytest.mark.parametrize("status", [LeadStatus.WON, LeadStatus.LOST])
def test_closed_leads_are_not_chased(status):
    lead = make_lead(created_days_ago=90, status=status)

    assert evaluate(lead, [], TODAY).bucket is FollowUpBucket.CLOSED


# ---------------------------------------------------------------- 預設提醒天數


def test_viewing_gets_the_shortest_default():
    """帶看完是最熱的時候，預設隔天就要追。"""
    assert default_follow_up_days(InteractionType.VIEWING) == 1


def test_note_defaults_to_tomorrow():
    """備註預設隔天再提醒。

    「備註」是個大雜燴 —— 可能是「致電未接」，也可能是「客戶說下週回覆」。
    系統分不出來，所以往保守的方向猜：假設還沒聯絡上，隔天再試。

    業務知道不用那麼急，自己改成 7 天就好。
    規則在這裡只是「建議的預設值」，不是「決定」。
    """
    assert default_follow_up_days(InteractionType.NOTE) == 1


def test_every_interaction_type_has_a_default():
    """漏掉一種類型，那種互動就會拿到一個沒人想過的天數。"""
    for type_ in InteractionType:
        assert type_ in DEFAULT_FOLLOW_UP_DAYS


# ---------------------------------------------------------------- 真的接上了嗎


def test_recording_an_interaction_sets_the_reminder(client):
    lead = client.post(f"{PREFIX}/leads", json={"name": "王先生"}).json()
    assert lead["next_follow_up_at"] is None

    client.post(
        f"{PREFIX}/leads/{lead['id']}/interactions",
        json={"type": "VIEWING", "content": "帶看兩間"},
    )
    after = client.get(f"{PREFIX}/leads/{lead['id']}").json()

    # 帶看的預設是隔天
    expected = date.today() + timedelta(days=1)
    assert after["next_follow_up_at"] == expected.isoformat()


def test_the_salesperson_can_override_the_default(client):
    """客戶說「我下週三再回你」，業務填 7 天 —— 規則猜不到那句話。"""
    lead = client.post(f"{PREFIX}/leads", json={"name": "王先生"}).json()

    client.post(
        f"{PREFIX}/leads/{lead['id']}/interactions",
        json={
            "type": "CALL",
            "content": "客戶說下週三再回覆",
            "next_follow_up_days": 7,
        },
    )
    after = client.get(f"{PREFIX}/leads/{lead['id']}").json()

    expected = date.today() + timedelta(days=7)
    assert after["next_follow_up_at"] == expected.isoformat()


def test_muting_through_an_interaction(client):
    lead = client.post(f"{PREFIX}/leads", json={"name": "王先生"}).json()

    client.post(
        f"{PREFIX}/leads/{lead['id']}/interactions",
        json={"type": "CALL", "content": "客戶決定不買了", "mute_follow_up": True},
    )
    after = client.get(f"{PREFIX}/leads/{lead['id']}").json()

    assert after["follow_up_muted"] is True
    assert after["next_follow_up_at"] is None


def test_a_new_interaction_unmutes(client):
    """業務又開始跟這個客戶了，靜音就該自動解除。

    否則業務會納悶「我明明有在跟，為什麼都沒提醒我」。
    """
    lead = client.post(f"{PREFIX}/leads", json={"name": "王先生"}).json()
    client.post(
        f"{PREFIX}/leads/{lead['id']}/interactions",
        json={"type": "CALL", "content": "先不找了", "mute_follow_up": True},
    )

    client.post(
        f"{PREFIX}/leads/{lead['id']}/interactions",
        json={"type": "CALL", "content": "客戶又回來了"},
    )
    after = client.get(f"{PREFIX}/leads/{lead['id']}").json()

    assert after["follow_up_muted"] is False
    assert after["next_follow_up_at"] is not None


# ---------------------------------------------------------------- 清單 API


def test_follow_up_list_separates_the_two_kinds(client, db_session):
    """兩堆要分開回，不能混成一份排序好的名單。"""
    from app.models.lead import Lead

    never_contacted = client.post(f"{PREFIX}/leads", json={"name": "沒人聯絡過"}).json()
    contacted = client.post(f"{PREFIX}/leads", json={"name": "聯絡過但逾期"}).json()
    client.post(
        f"{PREFIX}/leads/{contacted['id']}/interactions",
        json={"type": "CALL", "content": "聊過了"},
    )

    # 把時間往回撥，模擬「已經過了好幾天」
    stale = datetime.now(timezone.utc) - timedelta(days=5)
    db_session.get(Lead, never_contacted["id"]).created_at = stale
    db_session.get(Lead, contacted["id"]).next_follow_up_at = date.today() - timedelta(
        days=2
    )
    db_session.commit()

    body = client.get(f"{PREFIX}/leads/follow-ups").json()

    assert [i["lead"]["name"] for i in body["new_uncontacted"]] == ["沒人聯絡過"]
    assert [i["lead"]["name"] for i in body["due"]] == ["聯絡過但逾期"]


def test_muted_leads_are_counted_but_not_listed(client):
    """關掉提醒的客戶不能出現在待辦清單裡，但要讓業務知道有幾個。

    完全不顯示的話，某天業務會納悶「那個客戶怎麼再也沒出現過」。
    """
    lead = client.post(f"{PREFIX}/leads", json={"name": "先不找了"}).json()
    client.post(
        f"{PREFIX}/leads/{lead['id']}/interactions",
        json={"type": "CALL", "content": "暫時不找了", "mute_follow_up": True},
    )

    body = client.get(f"{PREFIX}/leads/follow-ups").json()

    listed = [i["lead"]["name"] for i in body["new_uncontacted"] + body["due"]]
    assert "先不找了" not in listed
    assert body["muted_count"] == 1


def test_longer_overdue_sorts_first(client, db_session):
    from app.models.lead import Lead

    a = client.post(f"{PREFIX}/leads", json={"name": "拖兩天"}).json()
    b = client.post(f"{PREFIX}/leads", json={"name": "拖十天"}).json()
    for lead_id in (a["id"], b["id"]):
        client.post(
            f"{PREFIX}/leads/{lead_id}/interactions",
            json={"type": "CALL", "content": "聊過了"},
        )

    db_session.get(Lead, a["id"]).next_follow_up_at = date.today() - timedelta(days=2)
    db_session.get(Lead, b["id"]).next_follow_up_at = date.today() - timedelta(days=10)
    db_session.commit()

    body = client.get(f"{PREFIX}/leads/follow-ups").json()

    assert [i["lead"]["name"] for i in body["due"]] == ["拖十天", "拖兩天"]


def test_follow_ups_only_include_your_own_leads(client, other_client):
    client.post(f"{PREFIX}/leads", json={"name": "業務甲的客戶"})

    body = other_client.get(f"{PREFIX}/leads/follow-ups").json()

    assert body["new_uncontacted"] == []
    assert body["due"] == []


def test_follow_ups_requires_login(anon_client):
    assert anon_client.get(f"{PREFIX}/leads/follow-ups").status_code == 401
