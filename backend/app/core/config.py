"""集中管理設定值。

所有環境變數只在這裡讀一次，其他程式一律 from app.core.config import settings。
這樣做的理由：日後要換資料庫、換 LLM 供應商，只要改這一個檔案。
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    PROJECT_NAME: str = "AI CRM Sales Copilot"
    API_V1_PREFIX: str = "/api/v1"

    DATABASE_URL: str

    JWT_SECRET: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # Sprint 3 才會用到
    OPENAI_API_KEY: str = ""


settings = Settings()
