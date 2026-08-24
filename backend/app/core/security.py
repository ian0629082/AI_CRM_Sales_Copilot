"""密碼雜湊與 JWT 處理。

只有這個檔案知道密碼是怎麼存的、token 是怎麼簽的。
其他程式一律透過這裡的函式，日後要換演算法只需要改這一處。
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import settings

# bcrypt 演算法本身只吃前 72 bytes，超過的部分會被無聲忽略。
# 注意是 bytes 不是字元：中文一個字 3 bytes，所以 24 個中文字就會超過。
BCRYPT_MAX_BYTES = 72


def hash_password(password: str) -> str:
    """把明文密碼轉成 bcrypt hash。

    bcrypt 會自動產生並內嵌 salt，所以同一個密碼每次 hash 出來都不一樣，
    也因此無法用彩虹表反查。
    """
    password_bytes = password.encode("utf-8")
    if len(password_bytes) > BCRYPT_MAX_BYTES:
        # 寧可明確報錯，也不要讓使用者以為設了長密碼、實際只有前 72 bytes 生效
        raise ValueError(
            f"密碼長度不可超過 {BCRYPT_MAX_BYTES} bytes（中文一字約 3 bytes）"
        )
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    """驗證明文密碼是否符合 hash。"""
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"), password_hash.encode("utf-8")
        )
    except ValueError:
        # hash 格式損壞時不該讓整支 API 500，當作驗證失敗處理
        return False


def create_access_token(subject: str | int) -> str:
    """簽發 JWT。

    subject 放 user id。刻意不放 email 或姓名：
    token 內容只是 base64 編碼、不是加密，任何人都能解開來看。
    """
    now = datetime.now(UTC)
    payload = {
        "sub": str(subject),
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any] | None:
    """驗證並解開 JWT，失敗（過期、簽章錯誤、格式錯誤）一律回傳 None。"""
    try:
        return jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
    except jwt.PyJWTError:
        return None
