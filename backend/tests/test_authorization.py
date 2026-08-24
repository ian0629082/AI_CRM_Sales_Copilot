"""授權測試：每位業務只能看到自己的客戶。

這是 CRM 最基本的資料隔離要求。目前系統只有「業務」一種角色，
沒有主管視角，所以規則很單純：不是你的客戶，你就當它不存在。

刻意回 404 而不是 403 —— 回 403 等於承認「這個 id 存在，只是不給你看」，
攻擊者就能靠列舉 id 推測系統裡有多少客戶。
"""

import pytest
from fastapi.testclient import TestClient

PREFIX = "/api/v1"


# ---------- 未登入一律擋掉 ----------


@pytest.mark.parametrize(
    "method, path",
    [
        ("post", "/leads"),
        ("get", "/leads"),
        ("get", "/leads/1"),
        ("patch", "/leads/1"),
        ("delete", "/leads/1"),
        ("post", "/leads/1/interactions"),
        ("get", "/leads/1/interactions"),
        ("delete", "/leads/1/interactions/1"),
        ("get", "/auth/me"),
    ],
)
def test_endpoints_require_authentication(
    anon_client: TestClient, method: str, path: str
):
    # 用 request() 而非 client.get()：httpx 的 get/delete 不接受 json 參數
    resp = anon_client.request(method.upper(), f"{PREFIX}{path}", json={})
    assert resp.status_code == 401, f"{method.upper()} {path} 沒有要求登入"


def test_malformed_authorization_header_is_rejected(anon_client: TestClient):
    resp = anon_client.get(
        f"{PREFIX}/leads", headers={"Authorization": "this-is-not-bearer"}
    )
    assert resp.status_code == 401


# ---------- 建立的客戶歸屬於自己 ----------


def test_created_lead_belongs_to_current_user(client: TestClient):
    lead = client.post(f"{PREFIX}/leads", json={"name": "我的客戶"}).json()
    me = client.get(f"{PREFIX}/auth/me").json()

    assert lead["owner_id"] == me["id"]


# ---------- 看不到別人的客戶 ----------


def test_lead_list_only_shows_own_leads(client: TestClient, other_client: TestClient):
    client.post(f"{PREFIX}/leads", json={"name": "甲的客戶"})
    other_client.post(f"{PREFIX}/leads", json={"name": "乙的客戶"})

    a_list = client.get(f"{PREFIX}/leads").json()
    b_list = other_client.get(f"{PREFIX}/leads").json()

    assert a_list["total"] == 1
    assert a_list["items"][0]["name"] == "甲的客戶"
    assert b_list["total"] == 1
    assert b_list["items"][0]["name"] == "乙的客戶"


def test_cannot_read_another_users_lead(client: TestClient, other_client: TestClient):
    lead_id = client.post(f"{PREFIX}/leads", json={"name": "甲的客戶"}).json()["id"]

    assert other_client.get(f"{PREFIX}/leads/{lead_id}").status_code == 404


def test_cannot_update_another_users_lead(client: TestClient, other_client: TestClient):
    lead_id = client.post(f"{PREFIX}/leads", json={"name": "甲的客戶"}).json()["id"]

    resp = other_client.patch(f"{PREFIX}/leads/{lead_id}", json={"name": "被改掉了"})
    assert resp.status_code == 404

    # 確認資料真的沒被動到
    assert client.get(f"{PREFIX}/leads/{lead_id}").json()["name"] == "甲的客戶"


def test_cannot_delete_another_users_lead(client: TestClient, other_client: TestClient):
    lead_id = client.post(f"{PREFIX}/leads", json={"name": "甲的客戶"}).json()["id"]

    assert other_client.delete(f"{PREFIX}/leads/{lead_id}").status_code == 404
    assert client.get(f"{PREFIX}/leads/{lead_id}").status_code == 200


def test_keyword_search_does_not_leak_other_users_leads(
    client: TestClient, other_client: TestClient
):
    """搜尋也必須受隔離限制，不能繞過。"""
    client.post(f"{PREFIX}/leads", json={"name": "王大明", "phone": "0911111111"})

    resp = other_client.get(f"{PREFIX}/leads", params={"keyword": "王大明"}).json()
    assert resp["total"] == 0


def test_status_filter_does_not_leak_other_users_leads(
    client: TestClient, other_client: TestClient
):
    client.post(f"{PREFIX}/leads", json={"name": "甲的客戶"})

    resp = other_client.get(f"{PREFIX}/leads", params={"status": "NEW"}).json()
    assert resp["total"] == 0


# ---------- 互動紀錄的權限跟著 Lead 走 ----------


def test_cannot_list_interactions_of_another_users_lead(
    client: TestClient, other_client: TestClient
):
    lead_id = client.post(f"{PREFIX}/leads", json={"name": "甲的客戶"}).json()["id"]
    client.post(
        f"{PREFIX}/leads/{lead_id}/interactions",
        json={"type": "CALL", "content": "機密通話內容"},
    )

    resp = other_client.get(f"{PREFIX}/leads/{lead_id}/interactions")
    assert resp.status_code == 404
    assert "機密通話內容" not in resp.text


def test_cannot_add_interaction_to_another_users_lead(
    client: TestClient, other_client: TestClient
):
    lead_id = client.post(f"{PREFIX}/leads", json={"name": "甲的客戶"}).json()["id"]

    resp = other_client.post(
        f"{PREFIX}/leads/{lead_id}/interactions",
        json={"type": "NOTE", "content": "亂塞的紀錄"},
    )
    assert resp.status_code == 404

    # 甲的 Timeline 必須維持空的
    assert client.get(f"{PREFIX}/leads/{lead_id}/interactions").json() == []


def test_cannot_delete_interaction_of_another_users_lead(
    client: TestClient, other_client: TestClient
):
    lead_id = client.post(f"{PREFIX}/leads", json={"name": "甲的客戶"}).json()["id"]
    interaction_id = client.post(
        f"{PREFIX}/leads/{lead_id}/interactions",
        json={"type": "CALL", "content": "重要紀錄"},
    ).json()["id"]

    resp = other_client.delete(
        f"{PREFIX}/leads/{lead_id}/interactions/{interaction_id}"
    )
    assert resp.status_code == 404

    # 紀錄必須完好無損
    assert len(client.get(f"{PREFIX}/leads/{lead_id}/interactions").json()) == 1


def test_lead_detail_of_another_user_leaks_nothing(
    client: TestClient, other_client: TestClient
):
    """Lead Detail 會一併回傳互動紀錄，要確認整包都不會外洩。"""
    lead_id = client.post(
        f"{PREFIX}/leads", json={"name": "甲的客戶", "phone": "0911111111"}
    ).json()["id"]
    client.post(
        f"{PREFIX}/leads/{lead_id}/interactions",
        json={"type": "VIEWING", "content": "帶看紀錄"},
    )

    resp = other_client.get(f"{PREFIX}/leads/{lead_id}")
    assert resp.status_code == 404
    for secret in ["甲的客戶", "0911111111", "帶看紀錄"]:
        assert secret not in resp.text
