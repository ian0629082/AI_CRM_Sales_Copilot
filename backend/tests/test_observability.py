"""可觀測性與錯誤處理的測試（Sprint 6）。

這一份測的不是「功能對不對」，而是**「出事的時候，我們看不看得見」**。
這種東西最容易寫完就忘記驗證 —— 因為它平常不會被觸發，
等到正式環境真的出事那天才發現 log 裡什麼都沒有，就來不及了。
"""

import logging

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.core.logging import (
    RequestContextFilter,
    mask_email,
    new_request_id,
    set_request_context,
)
from app.core.middleware import (
    REQUEST_ID_HEADER,
    claimed_client_ip,
    forwarded_chain,
    trusted_client_ip,
)
from app.main import app
from tests.conftest import PREFIX


# ----------------------------------------------------------------------
# email 遮罩
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("sales.a@example.com", "sa***@example.com"),
        ("a@gmail.com", "a***@gmail.com"),
        ("", "-"),
        # 不是 email 格式（使用者亂填）時整串遮掉，不去猜它是什麼
        ("not-an-email", "no***"),
    ],
)
def test_mask_email(raw: str, expected: str):
    assert mask_email(raw) == expected


def test_mask_email_keeps_same_account_identifiable():
    """遮罩之後，同一個帳號的多次失敗仍然長得一樣。

    這正是遮罩與「乾脆不記」的差別：
    「有人針對這個帳號反覆嘗試」看得出來，但撿到 log 的人拿不到完整地址。
    """
    assert mask_email("victim@example.com") == mask_email("victim@example.com")
    assert mask_email("victim@example.com") != mask_email("other@example.com")


def test_login_failure_does_not_log_full_email(
    anon_client: TestClient, caplog: pytest.LogCaptureFixture
):
    email = "sales.a@example.com"
    anon_client.post(
        f"{PREFIX}/auth/register",
        json={"name": "業務甲", "email": email, "password": "password123"},
    )

    with caplog.at_level(logging.WARNING):
        resp = anon_client.post(
            f"{PREFIX}/auth/login", json={"email": email, "password": "wrong-password"}
        )

    assert resp.status_code == 401
    logged = caplog.text
    assert email not in logged, "完整 email 不可以出現在 log 裡"
    assert "sa***@example.com" in logged, "遮罩後的 email 要留著，否則查不出是誰在試"


def test_login_failure_response_still_hides_whether_account_exists(
    anon_client: TestClient,
):
    """遮罩是 log 這一側的防護，不能動到 API 回應那一側原本的防護。"""
    anon_client.post(
        f"{PREFIX}/auth/register",
        json={"name": "業務甲", "email": "exists@example.com", "password": "password123"},
    )

    wrong_password = anon_client.post(
        f"{PREFIX}/auth/login",
        json={"email": "exists@example.com", "password": "wrong-password"},
    )
    no_such_account = anon_client.post(
        f"{PREFIX}/auth/login",
        json={"email": "nobody@example.com", "password": "wrong-password"},
    )

    assert wrong_password.status_code == no_such_account.status_code == 401
    assert wrong_password.json() == no_such_account.json()


# ----------------------------------------------------------------------
# request id
# ----------------------------------------------------------------------


def test_response_carries_request_id(anon_client: TestClient):
    """回寫 header 是這個機制的一半：使用者要看得到才回報得出來。"""
    resp = anon_client.get("/health")
    assert resp.headers.get(REQUEST_ID_HEADER)


def test_each_request_gets_a_different_id(anon_client: TestClient):
    first = anon_client.get("/health").headers[REQUEST_ID_HEADER]
    second = anon_client.get("/health").headers[REQUEST_ID_HEADER]
    assert first != second


def test_incoming_request_id_is_reused(anon_client: TestClient):
    """前面的閘道已經給過 id 就沿用，跨服務追查時才是同一條線。"""
    resp = anon_client.get("/health", headers={REQUEST_ID_HEADER: "abc12345"})
    assert resp.headers[REQUEST_ID_HEADER] == "abc12345"


def test_incoming_request_id_is_truncated(anon_client: TestClient):
    """這個值會進 log，不能讓外部塞一大段字進來洗版。"""
    resp = anon_client.get("/health", headers={REQUEST_ID_HEADER: "x" * 500})
    assert len(resp.headers[REQUEST_ID_HEADER]) == 64


def test_log_lines_within_one_request_share_the_id(
    anon_client: TestClient, caplog: pytest.LogCaptureFixture
):
    """同一次請求裡不同模組寫的 log，request_id 必須一致 —— 這是整套機制的重點。

    filter 必須在 log 發生的當下就套用（所以掛在 handler 上），
    不能等到事後才補：contextvar 的值只在那一次請求的執行脈絡裡有效，
    請求結束後再去讀，讀到的是測試主執行緒的預設值。
    """
    caplog.handler.addFilter(RequestContextFilter())

    with caplog.at_level(logging.INFO):
        resp = anon_client.post(
            f"{PREFIX}/auth/login",
            json={"email": "nobody@example.com", "password": "wrong-password"},
        )

    request_id = resp.headers[REQUEST_ID_HEADER]

    # auth_service 寫的那行「登入失敗」與 middleware 寫的那行「POST ... → 401」
    # 分屬不同模組、不同執行緒，但屬於同一次請求
    from_service = [r for r in caplog.records if "登入失敗" in r.getMessage()]
    from_middleware = [r for r in caplog.records if "/auth/login →" in r.getMessage()]
    assert from_service and from_middleware

    for record in from_service + from_middleware:
        assert record.request_id == request_id


def test_request_id_filter_survives_outside_a_request():
    """啟動階段與背景腳本沒有 request context，不能讓 log 本身丟例外。"""
    record = logging.LogRecord("x", logging.INFO, "x", 1, "msg", None, None)
    assert RequestContextFilter().filter(record) is True
    assert record.request_id == "-"


def test_new_request_id_is_short_and_unique():
    ids = {new_request_id() for _ in range(100)}
    assert len(ids) == 100
    assert all(len(i) == 8 for i in ids)


# ----------------------------------------------------------------------
# 來源 IP
# ----------------------------------------------------------------------


def _request_with(headers: dict[str, str], client: tuple[str, int] | None):
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": client,
    }
    return Request(scope)


def test_claimed_ip_is_what_the_caller_wrote():
    """第一段是「客戶端宣稱的」，查問題時有用，但不能拿來計數。

    實測過 Render：偽造 X-Forwarded-For: 1.2.3.4 之後，log 裡就是 1.2.3.4，
    平台不會覆蓋它。
    """
    req = _request_with({"X-Forwarded-For": "1.2.3.4, 61.223.40.235"}, ("10.0.0.1", 80))
    assert claimed_client_ip(req) == "1.2.3.4"


def test_trusted_ip_takes_the_last_hop():
    """最後一段是我們前面那一層代理寫的，是這串裡唯一不受外部控制的值。

    這正是節流要用的那個 —— 攻擊者可以在前面塞任意多個假 IP，
    但改不掉代理自己附加的那一段。
    """
    req = _request_with({"X-Forwarded-For": "1.2.3.4, 61.223.40.235"}, ("10.0.0.1", 80))
    assert trusted_client_ip(req) == "61.223.40.235"


def test_trusted_ip_ignores_a_long_forged_chain():
    """攻擊者塞一整串假的也沒用，取的仍然是最後那一段。"""
    forged = "1.1.1.1, 2.2.2.2, 3.3.3.3, 61.223.40.235"
    req = _request_with({"X-Forwarded-For": forged}, ("10.0.0.1", 80))
    assert trusted_client_ip(req) == "61.223.40.235"


def test_client_ip_falls_back_to_direct_connection():
    """本機開發或直連時沒有這個 header，退回 TCP 對端位址。"""
    assert trusted_client_ip(_request_with({}, ("127.0.0.1", 5000))) == "127.0.0.1"
    assert claimed_client_ip(_request_with({}, ("127.0.0.1", 5000))) == "127.0.0.1"


def test_client_ip_handles_missing_client():
    assert trusted_client_ip(_request_with({}, None)) == "-"


def test_forwarded_chain_counts_hops():
    """hops 是驗證「取最後一段」還對不對的依據。

    正式環境每個請求都應該固定是 1。哪天平台在前面多加一層，
    這個數字會變成 2 —— 那時候取到的就不再是客戶端，
    而症狀會是「節流突然把所有人一起鎖住」，沒有這個數字幾乎查不出來。
    """
    assert forwarded_chain(_request_with({"X-Forwarded-For": "1.1.1.1"}, None)) == [
        "1.1.1.1"
    ]
    assert forwarded_chain(_request_with({}, None)) == []
    # 空白與多餘的逗號不該算成一段
    assert forwarded_chain(
        _request_with({"X-Forwarded-For": " 1.1.1.1 , , 2.2.2.2 "}, None)
    ) == ["1.1.1.1", "2.2.2.2"]


# ----------------------------------------------------------------------
# 未預期的例外
# ----------------------------------------------------------------------


@pytest.fixture
def boom_client(anon_client: TestClient):
    """掛一條一定會爆炸的路由，用來驗證兜底的錯誤處理。

    raise_server_exceptions=False 是關鍵：TestClient 預設會把例外原樣丟回
    測試程式（那在平常很有用，看得到真正的錯誤），
    但這裡要測的正是「例外被攔下來之後回給前端的樣子」。
    """

    @app.get("/__boom__")
    def boom():
        raise RuntimeError("資料庫連線密碼是 hunter2")  # 故意放敏感字串

    client = TestClient(anon_client.app, raise_server_exceptions=False)
    yield client
    # 測完把臨時路由拿掉，不要污染其他測試
    app.router.routes = [r for r in app.router.routes if getattr(r, "path", "") != "/__boom__"]


def test_unexpected_error_returns_500_without_leaking_details(boom_client: TestClient):
    resp = boom_client.get("/__boom__")

    assert resp.status_code == 500
    body = resp.json()
    assert body["detail"] == "伺服器發生非預期的錯誤，請稍後再試"
    # 內部細節一個字都不能出現在回應裡
    assert "hunter2" not in resp.text
    assert "RuntimeError" not in resp.text
    assert "Traceback" not in resp.text


def test_unexpected_error_gives_the_user_something_to_report(boom_client: TestClient):
    """對外少說，但要留一條線索，否則使用者回報時我們無從查起。"""
    resp = boom_client.get("/__boom__")
    assert resp.json()["request_id"] == resp.headers[REQUEST_ID_HEADER]


def test_unexpected_error_writes_the_traceback_to_log(
    boom_client: TestClient, caplog: pytest.LogCaptureFixture
):
    """對內要說完：正式環境沒有終端機，堆疊沒進 log 就等於不存在。

    這一條同時守著一個很容易踩的坑 —— 同步的錯誤處理器是在 threadpool 裡跑的，
    `logger.exception()` 在那裡抓不到當下的例外，只會留下一句 "NoneType: None"。
    """
    with caplog.at_level(logging.ERROR):
        boom_client.get("/__boom__")

    assert "Traceback" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "hunter2" in caplog.text, "內部細節必須留在 log 裡，只是不能給前端"


def test_unexpected_error_keeps_cors_headers(boom_client: TestClient):
    """500 也必須帶 CORS header，否則前端根本讀不到上面那個 request_id。

    這一條守的是中介層的掛載順序。Starlette 內建的錯誤處理器位在整個堆疊的
    最外面，它產生的回應不經過 CORSMiddleware —— 瀏覽器會直接擋掉整個回應，
    前端拿到的是一個沒有內容的網路錯誤，看起來像後端整台掛了。
    所以兜底要放在 CORS 的內層（見 main.py 掛載順序的註解）。
    """
    resp = boom_client.get("/__boom__", headers={"Origin": "http://localhost:3000"})

    assert resp.status_code == 500
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_unexpected_error_still_logs_the_request_line(
    boom_client: TestClient, caplog: pytest.LogCaptureFixture
):
    """爆炸的請求也要有那行「請求結束」的紀錄，否則 log 會停在半路。"""
    with caplog.at_level(logging.INFO):
        boom_client.get("/__boom__")

    assert any("/__boom__ → 500" in r.getMessage() for r in caplog.records)


def test_app_error_is_still_handled_separately(client: TestClient):
    """兜底的處理器不可以把原本分得很細的領域錯誤一起吃掉。"""
    resp = client.get(f"{PREFIX}/leads/999999")
    assert resp.status_code == 404
    assert "request_id" not in resp.json()


# ----------------------------------------------------------------------
# CORS 設定
# ----------------------------------------------------------------------


def test_cors_origins_parsed_from_settings():
    from app.core.config import Settings

    settings = Settings(
        DATABASE_URL="sqlite:///x.db",
        JWT_SECRET="x" * 32,
        CORS_ORIGINS="http://localhost:3000, https://my-app.vercel.app",
    )
    assert settings.cors_origin_list == [
        "http://localhost:3000",
        "https://my-app.vercel.app",
    ]


def test_cors_origins_ignores_trailing_separator():
    """環境變數是手打的，結尾多一個逗號不該變成一個空字串來源。"""
    from app.core.config import Settings

    settings = Settings(
        DATABASE_URL="sqlite:///x.db",
        JWT_SECRET="x" * 32,
        CORS_ORIGINS="http://localhost:3000,",
    )
    assert settings.cors_origin_list == ["http://localhost:3000"]


def test_request_context_is_isolated_between_requests():
    """直接設定 context 再讀回來，確認 contextvar 的存取沒有寫反。"""
    from app.core.logging import get_client_ip, get_request_id

    set_request_context("id-1", "203.0.113.1")
    assert get_request_id() == "id-1"
    assert get_client_ip() == "203.0.113.1"
