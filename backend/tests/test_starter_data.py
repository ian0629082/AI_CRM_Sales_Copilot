"""註冊時自動建立的範例客戶（Sprint 7）。

conftest 會把這些範例資料清掉，好讓其他測試從一張白紙開始 ——
所以這一份是**唯一**會看到它們的地方。少了它，那個功能被改壞了不會有人知道。

守四件事：

1. 新帳號真的拿得到範例客戶
2. 範例客戶屬於新註冊的那個人，不會跑到別人帳下
3. 分數是用同一套規則算出來的，不是寫死的
4. 建立失敗不能連累註冊本身
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.lead import Lead
from app.services.scoring_service import calculate_score
from app.services.starter_data import STARTER_LEADS

PREFIX = "/api/v1"


def _register(c: TestClient, email: str) -> dict:
    """註冊但**不**清掉範例資料 —— 這裡要看的就是那些資料。"""
    resp = c.post(
        f"{PREFIX}/auth/register",
        json={"name": "新業務", "email": email, "password": "password123"},
    )
    assert resp.status_code == 201, resp.text

    resp = c.post(
        f"{PREFIX}/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert resp.status_code == 200, resp.text
    c.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
    return resp.json()


def test_new_account_is_not_empty(anon_client: TestClient):
    """新帳號一進去就看得到東西。

    空的系統看不出它在做什麼 —— 使用者不知道 Lead Score 長什麼樣、
    不知道跟進建議按了會怎樣，也不知道自己該先做什麼。
    """
    _register(anon_client, "starter@example.com")

    items = anon_client.get(f"{PREFIX}/leads").json()["items"]
    assert len(items) == len(STARTER_LEADS)


def test_starter_leads_cover_different_situations(anon_client: TestClient):
    """範例客戶要看得出差別，不能六筆長得一樣。

    它們的用途是「讓人看懂」，所以分數要有高有低、狀態要不同 ——
    六筆都是同一種客戶的話，使用者仍然不知道這些欄位代表什麼。
    """
    _register(anon_client, "starter2@example.com")
    items = anon_client.get(f"{PREFIX}/leads").json()["items"]

    assert len({lead["status"] for lead in items}) >= 4
    assert len({lead["lead_level"] for lead in items}) >= 2

    scores = [lead["lead_score"] for lead in items]
    assert max(scores) - min(scores) >= 30, f"分數太接近，看不出差別：{scores}"


def test_scores_are_computed_not_hardcoded(
    anon_client: TestClient, db_session: Session
):
    """分數必須是規則算出來的。

    寫死的話，日後調整計分權重，範例資料會跟系統的實際行為對不上 ——
    而那正是最會誤導新使用者的地方：他看到的第一批數字是錯的。

    驗法是拿同一套規則重算一次，逐筆比對存下來的值。
    """
    _register(anon_client, "starter3@example.com")

    leads = db_session.query(Lead).all()
    assert len(leads) == len(STARTER_LEADS)

    for lead in leads:
        expected = calculate_score(lead)
        assert lead.lead_score == expected.score, lead.name
        assert lead.lead_level == expected.level, lead.name

    # 至少有一筆不是 0 分，否則「有算」這件事沒被驗到 ——
    # 一個永遠回 0 的實作也會通過上面的比對。
    assert any(lead.lead_score > 0 for lead in leads)


def test_each_user_gets_their_own(anon_client: TestClient):
    """範例客戶屬於註冊的那個人。

    owner_id 給錯的話症狀很難察覺：第二個人註冊之後看到的還是六筆，
    要等到兩個人互相看得到對方的資料才會發現。
    """
    _register(anon_client, "starter4@example.com")
    first = {lead["id"] for lead in anon_client.get(f"{PREFIX}/leads").json()["items"]}

    from app.main import app

    second_client = TestClient(app)
    _register(second_client, "starter5@example.com")
    second = {lead["id"] for lead in second_client.get(f"{PREFIX}/leads").json()["items"]}

    assert first & second == set(), "兩個人拿到同一批客戶"
    assert len(second) == len(STARTER_LEADS)


def test_registration_survives_starter_data_failure(
    anon_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """範例資料掛掉不能讓註冊失敗。

    範例資料是體驗上的加分，「帳號建好了卻登不進去」是功能上的故障，
    兩者的嚴重程度差很多。
    """
    from app.services import starter_data

    def boom(*args, **kwargs):
        raise RuntimeError("假裝這裡壞了")

    monkeypatch.setattr(starter_data, "create_for", boom)

    resp = anon_client.post(
        f"{PREFIX}/auth/register",
        json={"name": "倒楣的人", "email": "unlucky@example.com", "password": "password123"},
    )
    assert resp.status_code == 201, resp.text

    # 而且登得進去
    resp = anon_client.post(
        f"{PREFIX}/auth/login",
        json={"email": "unlucky@example.com", "password": "password123"},
    )
    assert resp.status_code == 200
