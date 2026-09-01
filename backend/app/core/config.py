"""集中管理設定值。

所有環境變數只在這裡讀一次，其他程式一律 from app.core.config import settings。
這樣做的理由：日後要換資料庫、換 LLM 供應商，只要改這一個檔案。
"""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# JWT 密鑰的最低長度。太短的密鑰可以被暴力破解，
# 一旦被破解，攻擊者就能自行簽發任何使用者的 token。
MIN_JWT_SECRET_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # 驗證失敗時不要把讀到的值印出來。
        #
        # 這條是部署時實際踩到的：Render 上少設了 DATABASE_URL，
        # pydantic 的錯誤訊息就把「目前已經讀到的設定」整個 dict 附在後面，
        # 於是 JWT_SECRET 的值被印進 build log。
        #
        # 也就是說，少設一個環境變數的懲罰不是「啟動失敗」而已，
        # 是「其餘所有祕密一起曝光」—— 而看得到 build log 的人
        # 比看得到資料庫的人多得多（雲端平台的網頁面板、CI 輸出、
        # 卡關時貼給別人求助的截圖）。
        #
        # 關掉之後訊息仍然會講清楚是哪個欄位缺了，查問題需要的資訊一點沒少。
        hide_input_in_errors=True,
    )

    PROJECT_NAME: str = "AI CRM Sales Copilot"
    API_V1_PREFIX: str = "/api/v1"

    DATABASE_URL: str

    # 允許跨來源請求的前端網址，多個用逗號分隔。
    # 寫成設定值而不是寫死 localhost：Sprint 7 前端上 Vercel 之後網址會變，
    # 那時若還寫死在程式裡，前端會整片拿到 CORS 錯誤，
    # 而且那種錯誤在瀏覽器上看起來像「後端掛了」，很難第一時間聯想到這裡。
    CORS_ORIGINS: str = "http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # --- AI（Sprint 3）---
    OPENAI_API_KEY: str = ""
    # 型號寫成環境變數而不是寫死在程式裡：換模型不必改一行程式碼，
    # Sprint 4 的 Evaluation 也能直接跑兩個模型比較準確率與成本。
    OPENAI_MODEL: str = "gpt-5.4-mini"
    # 同步等待的 API 一定要設逾時，否則 OpenAI 卡住時會把後端的連線一起卡死。
    OPENAI_TIMEOUT_SECONDS: float = 30.0

    @field_validator("JWT_SECRET")
    @classmethod
    def jwt_secret_must_be_strong(cls, v: str) -> str:
        """啟動時就擋掉弱密鑰，而不是等到上線被攻擊才發現。

        產生方式：python -c "import secrets; print(secrets.token_urlsafe(32))"
        """
        if len(v) < MIN_JWT_SECRET_LENGTH:
            raise ValueError(
                f"JWT_SECRET 長度至少需 {MIN_JWT_SECRET_LENGTH} 字元，"
                "請用 secrets.token_urlsafe(32) 產生"
            )
        return v


settings = Settings()
