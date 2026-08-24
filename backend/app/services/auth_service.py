"""註冊與登入的商業邏輯。"""

import logging

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, UnauthorizedError
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate, UserLogin

logger = logging.getLogger(__name__)


class AuthService:
    def __init__(self, db: Session):
        self.repo = UserRepository(db)

    def register(self, payload: UserCreate) -> User:
        email = payload.email.lower()

        if self.repo.get_by_email(email) is not None:
            raise ConflictError("此 email 已被註冊")

        user = self.repo.create(
            User(
                name=payload.name,
                email=email,
                # 明文密碼到這裡就結束了，只有 hash 會被存進資料庫
                password_hash=hash_password(payload.password),
            )
        )
        logger.info("新使用者註冊完成 user_id=%s", user.id)
        return user

    def login(self, payload: UserLogin) -> str:
        user = self.repo.get_by_email(payload.email)

        # 帳號不存在與密碼錯誤刻意回傳同一個訊息。
        # 若分開回應，攻擊者就能靠錯誤訊息逐一測出哪些 email 有註冊過。
        if user is None or not verify_password(payload.password, user.password_hash):
            logger.warning("登入失敗 email=%s", payload.email)
            raise UnauthorizedError("email 或密碼錯誤")

        logger.info("使用者登入成功 user_id=%s", user.id)
        return create_access_token(user.id)
