"""註冊與登入的測試。

除了正常流程，重點守住幾個安全性行為：
- 密碼絕不以明文入庫、絕不出現在 API 回應
- 錯誤訊息不洩漏「這個 email 有沒有註冊過」
- 過期或偽造的 token 一律拒絕
"""

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token
from app.models.user import User

PREFIX = "/api/v1"

VALID_USER = {
    "name": "林業務",
    "email": "lin@example.com",
    "password": "password123",
}


def test_register(anon_client: TestClient):
    resp = anon_client.post(f"{PREFIX}/auth/register", json=VALID_USER)
    assert resp.status_code == 201

    data = resp.json()
    assert data["name"] == "林業務"
    assert data["email"] == "lin@example.com"
    assert data["id"] > 0


def test_register_response_never_contains_password(anon_client: TestClient):
    """回應裡不能出現密碼或密碼雜湊，任何形式都不行。"""
    resp = anon_client.post(f"{PREFIX}/auth/register", json=VALID_USER)

    assert "password" not in resp.json()
    assert "password_hash" not in resp.json()
    assert "password123" not in resp.text


def test_password_is_hashed_in_database(anon_client: TestClient, db_session: Session):
    """直接查資料庫確認存的是 bcrypt hash，不是明文。"""
    anon_client.post(f"{PREFIX}/auth/register", json=VALID_USER)

    user = db_session.query(User).filter(User.email == "lin@example.com").one()
    assert user.password_hash != "password123"
    assert user.password_hash.startswith("$2b$")  # bcrypt 的格式標記


def test_register_duplicate_email(anon_client: TestClient):
    anon_client.post(f"{PREFIX}/auth/register", json=VALID_USER)

    resp = anon_client.post(f"{PREFIX}/auth/register", json=VALID_USER)
    assert resp.status_code == 409


def test_register_email_is_case_insensitive(anon_client: TestClient):
    """Lin@Example.com 與 lin@example.com 必須視為同一個帳號。"""
    anon_client.post(f"{PREFIX}/auth/register", json=VALID_USER)

    resp = anon_client.post(
        f"{PREFIX}/auth/register", json={**VALID_USER, "email": "Lin@Example.com"}
    )
    assert resp.status_code == 409


def test_can_login_with_different_email_casing(anon_client: TestClient):
    anon_client.post(f"{PREFIX}/auth/register", json=VALID_USER)

    resp = anon_client.post(
        f"{PREFIX}/auth/login",
        json={"email": "LIN@EXAMPLE.COM", "password": "password123"},
    )
    assert resp.status_code == 200


@pytest.mark.parametrize(
    "payload, reason",
    [
        ({**VALID_USER, "email": "not-an-email"}, "email 格式錯誤"),
        ({**VALID_USER, "password": "short"}, "密碼太短"),
        ({**VALID_USER, "name": ""}, "姓名空白"),
        ({**VALID_USER, "password": "中" * 25}, "中文密碼超過 bcrypt 的 72 bytes"),
    ],
)
def test_register_validation(anon_client: TestClient, payload: dict, reason: str):
    resp = anon_client.post(f"{PREFIX}/auth/register", json=payload)
    assert resp.status_code == 422, reason


def test_login_returns_token(anon_client: TestClient):
    anon_client.post(f"{PREFIX}/auth/register", json=VALID_USER)

    resp = anon_client.post(
        f"{PREFIX}/auth/login",
        json={"email": VALID_USER["email"], "password": VALID_USER["password"]},
    )
    assert resp.status_code == 200

    data = resp.json()
    assert data["token_type"] == "bearer"
    payload = jwt.decode(
        data["access_token"], settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
    )
    assert "sub" in payload and "exp" in payload


def test_login_wrong_password_and_unknown_email_give_same_message(
    anon_client: TestClient,
):
    """錯誤訊息必須一致。

    若「帳號不存在」與「密碼錯誤」回不同訊息，
    攻擊者就能靠這個差異逐一測出哪些 email 註冊過（帳號枚舉）。
    """
    anon_client.post(f"{PREFIX}/auth/register", json=VALID_USER)

    wrong_password = anon_client.post(
        f"{PREFIX}/auth/login",
        json={"email": VALID_USER["email"], "password": "wrong-password"},
    )
    unknown_email = anon_client.post(
        f"{PREFIX}/auth/login",
        json={"email": "nobody@example.com", "password": "password123"},
    )

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json()["detail"] == unknown_email.json()["detail"]


def test_me_returns_current_user(client: TestClient):
    resp = client.get(f"{PREFIX}/auth/me")
    assert resp.status_code == 200
    assert resp.json()["email"] == "sales.a@example.com"


def test_me_without_token(anon_client: TestClient):
    assert anon_client.get(f"{PREFIX}/auth/me").status_code == 401


@pytest.mark.parametrize(
    "token",
    [
        "not-a-jwt",
        "a.b.c",
        # 用別的密鑰簽出來的 token，格式正確但簽章不對
        jwt.encode({"sub": "1"}, "wrong-secret-key", algorithm="HS256"),
    ],
)
def test_me_rejects_invalid_token(anon_client: TestClient, token: str):
    resp = anon_client.get(
        f"{PREFIX}/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 401


def test_me_rejects_expired_token(anon_client: TestClient, monkeypatch):
    """把有效期設成負值來簽出一個已過期的 token。"""
    anon_client.post(f"{PREFIX}/auth/register", json=VALID_USER)
    monkeypatch.setattr(settings, "ACCESS_TOKEN_EXPIRE_MINUTES", -1)
    expired_token = create_access_token(1)

    resp = anon_client.get(
        f"{PREFIX}/auth/me", headers={"Authorization": f"Bearer {expired_token}"}
    )
    assert resp.status_code == 401


def test_token_of_deleted_user_is_rejected(
    anon_client: TestClient, db_session: Session
):
    """token 還沒過期，但帳號已經被刪掉時必須拒絕。

    這就是 get_current_user 仍要查一次資料庫的原因 ——
    只驗簽章是不夠的。
    """
    anon_client.post(f"{PREFIX}/auth/register", json=VALID_USER)
    token = anon_client.post(
        f"{PREFIX}/auth/login",
        json={"email": VALID_USER["email"], "password": VALID_USER["password"]},
    ).json()["access_token"]

    db_session.query(User).filter(User.email == VALID_USER["email"]).delete()
    db_session.commit()

    resp = anon_client.get(
        f"{PREFIX}/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 401
