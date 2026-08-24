"""使用者與認證的 API 資料契約。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.security import BCRYPT_MAX_BYTES


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=BCRYPT_MAX_BYTES)

    @field_validator("password")
    @classmethod
    def password_within_bcrypt_limit(cls, v: str) -> str:
        # max_length 算的是字元數，bcrypt 限制的是 bytes。
        # 中文一字 3 bytes，所以 25 個中文字就會超過而被無聲截斷 —— 這裡直接擋掉。
        if len(v.encode("utf-8")) > BCRYPT_MAX_BYTES:
            raise ValueError(
                f"密碼長度不可超過 {BCRYPT_MAX_BYTES} bytes（中文一字約 3 bytes）"
            )
        return v


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserRead(BaseModel):
    """回傳給前端的使用者資料。

    刻意不包含 password_hash —— schema 白名單就是最後一道防線，
    即使有人不小心把整個 model 丟出去，密碼雜湊也不會流出。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
