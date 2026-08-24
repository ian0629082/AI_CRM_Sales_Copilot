"""測試共用設定。

重點：測試不能碰到開發用的資料庫。
這裡用一個獨立的檔案型 SQLite，每個測試開始前重建，結束後刪掉。
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
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """把 app 的資料庫依賴換成測試用的 Session。

    這就是 Repository / Service 分層的回報：
    不需要改任何一行正式程式碼，就能把資料庫抽換掉。
    """

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
