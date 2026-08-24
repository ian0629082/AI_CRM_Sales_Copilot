"""Lead CRUD 的 API 測試（規劃書 Phase 17）。

這些測試守住 Sprint 1 的成果：日後加入 AI 與 Scoring 時，
如果不小心弄壞了基本的 CRM 功能，這裡會立刻紅燈。
"""

from fastapi.testclient import TestClient

PREFIX = "/api/v1"


def test_health(client: TestClient):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_create_lead_minimal(client: TestClient):
    """只給名字也要能建立 —— 業務接到電話時常常只知道姓名。"""
    resp = client.post(f"{PREFIX}/leads", json={"name": "王小明"})
    assert resp.status_code == 201

    data = resp.json()
    assert data["name"] == "王小明"
    assert data["status"] == "NEW"  # 新客戶預設進入漏斗第一關
    assert data["lead_score"] is None  # Scoring 是 Sprint 5 的事
    assert data["id"] > 0


def test_create_lead_full(client: TestClient):
    payload = {
        "name": "陳大文",
        "phone": "0912345678",
        "email": "chen@example.com",
        "source": "WEB_FORM",
        "raw_requirement": "想找西屯三房，預算2000萬，要有車位，自住，三個月內買。",
        "location": "西屯",
        "budget_max": 20000000,
        "rooms": 3,
        "parking": True,
        "purpose": "SELF_USE",
        "purchase_timeline": 3,
    }
    resp = client.post(f"{PREFIX}/leads", json=payload)
    assert resp.status_code == 201

    data = resp.json()
    assert data["location"] == "西屯"
    assert data["budget_max"] == 20000000
    assert data["parking"] is True
    assert data["purpose"] == "SELF_USE"


def test_create_lead_rejects_invalid_budget_range(client: TestClient):
    resp = client.post(
        f"{PREFIX}/leads",
        json={"name": "測試", "budget_min": 30000000, "budget_max": 10000000},
    )
    assert resp.status_code == 422


def test_create_lead_rejects_empty_name(client: TestClient):
    resp = client.post(f"{PREFIX}/leads", json={"name": ""})
    assert resp.status_code == 422


def test_get_lead(client: TestClient):
    created = client.post(f"{PREFIX}/leads", json={"name": "林小華"}).json()

    resp = client.get(f"{PREFIX}/leads/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "林小華"


def test_get_lead_not_found(client: TestClient):
    resp = client.get(f"{PREFIX}/leads/9999")
    assert resp.status_code == 404
    assert "9999" in resp.json()["detail"]


def test_list_leads_and_filter_by_status(client: TestClient):
    client.post(f"{PREFIX}/leads", json={"name": "A客戶"})
    b = client.post(f"{PREFIX}/leads", json={"name": "B客戶"}).json()
    client.patch(f"{PREFIX}/leads/{b['id']}", json={"status": "MEETING"})

    all_resp = client.get(f"{PREFIX}/leads").json()
    assert all_resp["total"] == 2

    filtered = client.get(f"{PREFIX}/leads", params={"status": "MEETING"}).json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["name"] == "B客戶"


def test_list_leads_search_by_keyword(client: TestClient):
    client.post(f"{PREFIX}/leads", json={"name": "王大明", "phone": "0911111111"})
    client.post(f"{PREFIX}/leads", json={"name": "李小美", "phone": "0922222222"})

    by_name = client.get(f"{PREFIX}/leads", params={"keyword": "王"}).json()
    assert by_name["total"] == 1

    by_phone = client.get(f"{PREFIX}/leads", params={"keyword": "0922"}).json()
    assert by_phone["total"] == 1
    assert by_phone["items"][0]["name"] == "李小美"


def test_patch_only_updates_provided_fields(client: TestClient):
    """PATCH 的關鍵行為：沒帶到的欄位必須保持原值，不能被洗成 null。"""
    created = client.post(
        f"{PREFIX}/leads",
        json={"name": "張先生", "phone": "0933333333", "location": "七期"},
    ).json()

    resp = client.patch(f"{PREFIX}/leads/{created['id']}", json={"status": "CONTACTED"})
    assert resp.status_code == 200

    data = resp.json()
    assert data["status"] == "CONTACTED"
    assert data["phone"] == "0933333333"
    assert data["location"] == "七期"


def test_delete_lead(client: TestClient):
    created = client.post(f"{PREFIX}/leads", json={"name": "待刪除"}).json()

    assert client.delete(f"{PREFIX}/leads/{created['id']}").status_code == 204
    assert client.get(f"{PREFIX}/leads/{created['id']}").status_code == 404


def test_delete_lead_not_found(client: TestClient):
    assert client.delete(f"{PREFIX}/leads/9999").status_code == 404
