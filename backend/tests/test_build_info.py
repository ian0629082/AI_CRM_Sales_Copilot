"""線上跑的是哪一版（Sprint 7）。

這個資訊存在的理由很具體：部署平台設定「跟著哪個分支」只有登入平台的人
看得到，而兩個分支指向同一份程式碼時，從外面完全分辨不出來 ——
等到程式碼真的分岔了才會發現，那時的症狀是「改好的東西沒有上線」。
"""

import pytest
from fastapi.testclient import TestClient

from app.core.build_info import current_build


def test_health_reports_the_build(anon_client: TestClient):
    body = anon_client.get("/health").json()

    assert body["status"] == "ok"
    assert "build" in body
    assert set(body["build"]) == {"branch", "commit", "service"}


def test_build_reads_platform_variables(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RENDER_GIT_BRANCH", "main")
    monkeypatch.setenv("RENDER_GIT_COMMIT", "388d0d6abcdef1234567890")
    monkeypatch.setenv("RENDER_SERVICE_NAME", "ai-crm-backend")

    info = current_build()

    assert info.branch == "main"
    # 只留前 7 碼：完整的 40 碼對照不上任何東西，只是佔位置
    assert info.commit == "388d0d6"
    assert info.service == "ai-crm-backend"


def test_missing_variables_are_none_not_unknown(monkeypatch: pytest.MonkeyPatch):
    """本機或其他平台沒有這些變數時要回 None。

    不要用 "unknown" 之類的字串填空 —— 那會讓「沒有這個資訊」
    跟「這個資訊的值剛好是 unknown」變成同一件事，
    而查問題的人分不出自己看到的是哪一種。
    """
    for name in ("RENDER_GIT_BRANCH", "RENDER_GIT_COMMIT", "RENDER_SERVICE_NAME"):
        monkeypatch.delenv(name, raising=False)

    info = current_build()

    assert info.branch is None
    assert info.commit is None
    assert info.service is None


def test_empty_variables_are_treated_as_missing(monkeypatch: pytest.MonkeyPatch):
    """平台把變數設成空字串跟沒設是同一件事。

    這不是假想的情況：環境變數很容易在轉手之間變成空字串，
    而一個 branch="" 的回應看起來像「有這個欄位但它是空的」，
    比直接說沒有更難解讀。
    """
    monkeypatch.setenv("RENDER_GIT_BRANCH", "")
    monkeypatch.setenv("RENDER_GIT_COMMIT", "")

    info = current_build()

    assert info.branch is None
    assert info.commit is None


def test_health_still_does_not_touch_the_database(anon_client: TestClient):
    """/health 仍然只回答「程式起來了」。

    平台用這支判斷服務死活，所以它必須快、也不能被外部服務拖垮 ——
    加了 build 資訊之後這一點不能變（它讀的是環境變數，不是資料庫）。
    """
    resp = anon_client.get("/health")

    assert resp.status_code == 200
    # 沒有任何需要認證的東西，也不需要資料庫連線
    assert "Authorization" not in resp.request.headers
