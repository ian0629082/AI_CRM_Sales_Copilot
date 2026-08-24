"""Interaction CRUD 的 API 測試。

除了基本的增刪查，特別守住兩件事：
1. 新增互動會把 NEW 的 Lead 自動推進為 CONTACTED，但不會倒退已進展的狀態
2. 不能透過別的客戶網址去動到不屬於他的互動紀錄
"""

from fastapi.testclient import TestClient

PREFIX = "/api/v1"


def _create_lead(client: TestClient, name: str = "測試客戶") -> int:
    return client.post(f"{PREFIX}/leads", json={"name": name}).json()["id"]


def test_create_interaction(client: TestClient):
    lead_id = _create_lead(client)

    resp = client.post(
        f"{PREFIX}/leads/{lead_id}/interactions",
        json={"type": "CALL", "content": "第一次電訪，客戶表示週末有空看房"},
    )
    assert resp.status_code == 201

    data = resp.json()
    assert data["type"] == "CALL"
    assert data["lead_id"] == lead_id
    assert data["content"] == "第一次電訪，客戶表示週末有空看房"


def test_create_interaction_advances_new_lead_to_contacted(client: TestClient):
    """業務接觸過客戶後，Lead 不該再停留在 NEW。"""
    lead_id = _create_lead(client)
    assert client.get(f"{PREFIX}/leads/{lead_id}").json()["status"] == "NEW"

    client.post(
        f"{PREFIX}/leads/{lead_id}/interactions",
        json={"type": "CALL", "content": "初次聯絡"},
    )

    assert client.get(f"{PREFIX}/leads/{lead_id}").json()["status"] == "CONTACTED"


def test_create_interaction_does_not_regress_advanced_status(client: TestClient):
    """已經談到 NEGOTIATING 的客戶，補記一通電話不該被退回 CONTACTED。"""
    lead_id = _create_lead(client)
    client.patch(f"{PREFIX}/leads/{lead_id}", json={"status": "NEGOTIATING"})

    client.post(
        f"{PREFIX}/leads/{lead_id}/interactions",
        json={"type": "NOTE", "content": "補記：上週已議價一次"},
    )

    assert client.get(f"{PREFIX}/leads/{lead_id}").json()["status"] == "NEGOTIATING"


def test_create_interaction_rejects_invalid_type(client: TestClient):
    lead_id = _create_lead(client)
    resp = client.post(
        f"{PREFIX}/leads/{lead_id}/interactions",
        json={"type": "TELEPATHY", "content": "心電感應"},
    )
    assert resp.status_code == 422


def test_create_interaction_rejects_empty_content(client: TestClient):
    lead_id = _create_lead(client)
    resp = client.post(
        f"{PREFIX}/leads/{lead_id}/interactions",
        json={"type": "NOTE", "content": ""},
    )
    assert resp.status_code == 422


def test_create_interaction_on_missing_lead(client: TestClient):
    resp = client.post(
        f"{PREFIX}/leads/9999/interactions",
        json={"type": "CALL", "content": "打給不存在的人"},
    )
    assert resp.status_code == 404


def test_list_interactions_is_newest_first(client: TestClient):
    """Timeline 必須由新到舊，業務打開頁面要先看到最近發生的事。"""
    lead_id = _create_lead(client)
    for content in ["第一通電話", "第二次帶看", "第三次議價"]:
        client.post(
            f"{PREFIX}/leads/{lead_id}/interactions",
            json={"type": "NOTE", "content": content},
        )

    items = client.get(f"{PREFIX}/leads/{lead_id}/interactions").json()
    assert [i["content"] for i in items] == ["第三次議價", "第二次帶看", "第一通電話"]


def test_list_interactions_on_missing_lead(client: TestClient):
    assert client.get(f"{PREFIX}/leads/9999/interactions").status_code == 404


def test_lead_detail_includes_interactions(client: TestClient):
    """Lead Detail 頁一次拿到客戶資料 + Timeline，不用打兩支 API。"""
    lead_id = _create_lead(client, "陳大文")
    client.post(
        f"{PREFIX}/leads/{lead_id}/interactions",
        json={"type": "VIEWING", "content": "帶看七期三房"},
    )

    data = client.get(f"{PREFIX}/leads/{lead_id}").json()
    assert data["name"] == "陳大文"
    assert len(data["interactions"]) == 1
    assert data["interactions"][0]["type"] == "VIEWING"


def test_lead_list_does_not_include_interactions(client: TestClient):
    """列表用輕量 schema，不該把互動紀錄一起撈出來。"""
    lead_id = _create_lead(client)
    client.post(
        f"{PREFIX}/leads/{lead_id}/interactions",
        json={"type": "NOTE", "content": "備註"},
    )

    items = client.get(f"{PREFIX}/leads").json()["items"]
    assert "interactions" not in items[0]


def test_delete_interaction(client: TestClient):
    lead_id = _create_lead(client)
    interaction_id = client.post(
        f"{PREFIX}/leads/{lead_id}/interactions",
        json={"type": "NOTE", "content": "打錯字的紀錄"},
    ).json()["id"]

    resp = client.delete(f"{PREFIX}/leads/{lead_id}/interactions/{interaction_id}")
    assert resp.status_code == 204
    assert client.get(f"{PREFIX}/leads/{lead_id}/interactions").json() == []


def test_cannot_delete_interaction_belonging_to_another_lead(client: TestClient):
    """A 客戶的網址不能刪掉 B 客戶的紀錄。"""
    lead_a = _create_lead(client, "A客戶")
    lead_b = _create_lead(client, "B客戶")
    interaction_b = client.post(
        f"{PREFIX}/leads/{lead_b}/interactions",
        json={"type": "CALL", "content": "B 的通話紀錄"},
    ).json()["id"]

    resp = client.delete(f"{PREFIX}/leads/{lead_a}/interactions/{interaction_b}")
    assert resp.status_code == 404

    # B 的紀錄必須完好無損
    assert len(client.get(f"{PREFIX}/leads/{lead_b}/interactions").json()) == 1


def test_deleting_lead_removes_its_interactions(client: TestClient):
    """刪除客戶時，附屬的互動紀錄要一起清掉，不能留下孤兒資料。"""
    lead_id = _create_lead(client)
    client.post(
        f"{PREFIX}/leads/{lead_id}/interactions",
        json={"type": "NOTE", "content": "會被一起刪掉"},
    )

    assert client.delete(f"{PREFIX}/leads/{lead_id}").status_code == 204
    assert client.get(f"{PREFIX}/leads/{lead_id}/interactions").status_code == 404
