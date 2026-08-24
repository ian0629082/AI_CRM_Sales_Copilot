"""資料庫連線與 Session 管理。

Engine 是連線池，整個程式只建立一次。
Session 是一次請求的工作單位，每個 API request 開一個、結束就關掉。
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    """所有 ORM model 的共同父類別。"""


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency：每個 request 拿到一個 Session，結束後自動關閉。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
