"""Alembic 執行環境設定。

兩個重點：

1. 連線字串一律從 app.core.config 讀（也就是 .env），
   絕對不寫進 alembic.ini —— ini 是要進版控的，裡面不能有資料庫密碼。
2. target_metadata 指向 app 的 Base，這樣 alembic 才能比對
   「model 現在長什麼樣」與「資料庫現在長什麼樣」，自動產生差異。
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings
from app.db.database import Base
from app.models import Interaction, Lead, User  # noqa: F401  匯入才會註冊到 Base

config = context.config

# 用 set_section_option 而非寫死在 ini，避免密碼外洩到版控
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """產生 SQL 檔而不實際連線（--sql 模式）。"""
    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """實際連上資料庫執行 migration。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # 預設不會偵測欄位型別變更，打開才抓得到 VARCHAR(50) -> VARCHAR(100) 這類改動
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
