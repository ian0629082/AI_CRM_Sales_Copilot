"""測試共用設定。

重點：測試不能碰到開發用的資料庫。
這裡用一個獨立的檔案型 SQLite，每個測試開始前重建，結束後刪掉。

三種 client：
- client        已登入的業務（絕大多數測試用這個）
- anon_client   未登入，用來驗證 API 真的有擋
- other_client  另一位業務，用來驗證看不到別人的客戶
"""

import os
import tempfile
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.database import Base, get_db
from app.main import app
from app.models import Interaction, Lead, User  # noqa: F401  讓 Base 認得這些表

PREFIX = "/api/v1"


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
        os.unlink(path)


@pytest.fixture
def anon_client(db_session: Session) -> Generator[TestClient, None, None]:
    """未登入的 client。

    把 app 的資料庫依賴換成測試用的 Session —— 這就是分層的回報：
    不需要改任何一行正式程式碼，就能把資料庫抽換掉。
    """

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _register_and_login(c: TestClient, name: str, email: str) -> str:
    """建立帳號並回傳 access token。

    註冊會自動帶進幾筆範例客戶（見 app/services/starter_data.py），
    這裡把它們刪掉，讓每個測試都從一張白紙開始。

    為什麼不乾脆在測試環境關掉那個功能：那樣「註冊會建立範例資料」
    這件事在測試裡就完全不存在了，改壞了也沒人知道。
    現在的做法是照正式流程跑完、再清空 ——
    範例資料本身由 test_starter_data.py 專門驗證。
    """
    resp = c.post(
        f"{PREFIX}/auth/register",
        json={"name": name, "email": email, "password": "password123"},
    )
    assert resp.status_code == 201, resp.text

    resp = c.post(
        f"{PREFIX}/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]

    # 清掉註冊時自動建立的範例客戶
    listed = c.get(f"{PREFIX}/leads", headers={"Authorization": f"Bearer {token}"})
    assert listed.status_code == 200, listed.text
    for lead in listed.json()["items"]:
        c.delete(
            f"{PREFIX}/leads/{lead['id']}",
            headers={"Authorization": f"Bearer {token}"},
        )

    return token


@pytest.fixture
def client(anon_client: TestClient) -> TestClient:
    """已登入的業務。token 直接掛在 header 上，測試裡不必每次手動帶。"""
    token = _register_and_login(anon_client, "業務甲", "sales.a@example.com")
    anon_client.headers["Authorization"] = f"Bearer {token}"
    return anon_client


@pytest.fixture
def other_client(client: TestClient, db_session: Session) -> TestClient:
    """另一位業務，共用同一個資料庫但持有不同 token。

    依賴 client fixture 是刻意的：確保「業務甲」已經存在，
    這樣才能測出兩個人的資料真的互相隔離。
    """
    c = TestClient(app)
    token = _register_and_login(c, "業務乙", "sales.b@example.com")
    c.headers["Authorization"] = f"Bearer {token}"
    return c


@pytest.fixture(autouse=True)
def _fast_bcrypt(monkeypatch):
    """測試時把 bcrypt 的成本因子降到最低。

    bcrypt 刻意設計成計算緩慢（預設 12 rounds，約 0.3 秒一次），
    這在正式環境是必要的防護，但測試裡每次註冊都要付這個代價，
    整套測試會從幾秒膨脹到幾十秒。

    只調降測試環境，正式環境仍使用 bcrypt 的預設值。
    """
    import bcrypt

    real_gensalt = bcrypt.gensalt
    monkeypatch.setattr(bcrypt, "gensalt", lambda rounds=4, **kw: real_gensalt(4))
