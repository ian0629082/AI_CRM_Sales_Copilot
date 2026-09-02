"""註冊與登入的商業邏輯。"""

import logging

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, UnauthorizedError
from app.core.logging import mask_email
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate, UserLogin
from app.services import starter_data

logger = logging.getLogger(__name__)


class AuthService:
    def __init__(self, db: Session):
        self.db = db
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

        # 新帳號進去是全空的：列表沒東西、Dashboard 全是零、漏斗沒有形狀。
        # 一個空的系統看不出它在做什麼，使用者也不知道自己該先做什麼。
        #
        # 失敗不能連累註冊。範例資料是體驗上的加分，
        # 而「帳號建好了但登不進去」是功能上的故障 —— 兩者的嚴重程度差很多。
        try:
            count = starter_data.create_for(self.db, user)
            self.db.commit()
            logger.info("替 user_id=%s 建立了 %s 筆範例客戶", user.id, count)
        except Exception:
            self.db.rollback()
            # 用 exception 記完整堆疊：這種錯不會有人回報
            # （使用者只會覺得「怎麼是空的」），只能靠 log 自己發現。
            logger.exception("建立範例客戶失敗 user_id=%s，註冊本身不受影響", user.id)

        logger.info("新使用者註冊完成 user_id=%s", user.id)
        return user

    def login(self, payload: UserLogin) -> str:
        user = self.repo.get_by_email(payload.email)

        # 帳號不存在與密碼錯誤刻意回傳同一個訊息。
        # 若分開回應，攻擊者就能靠錯誤訊息逐一測出哪些 email 有註冊過。
        if user is None or not verify_password(payload.password, user.password_hash):
            # email 遮罩後才進 log。這跟上面那條「訊息刻意一致」防的是同一件事
            # （不要洩漏誰有註冊過），只是戰場不同：API 回應守得住，
            # log 卻會累積成一份「有人試過的帳號清單」，而且看得到 log 的人更多。
            #
            # 這裡不記來源 IP，不是因為不需要，而是因為不必記在這裡 ——
            # 這一行跟 middleware 記的那一行共用同一個 request_id，
            # 那一行有完整的 IP。Service 層因此不必知道 HTTP 的存在。
            logger.warning("登入失敗 email=%s", mask_email(payload.email))
            raise UnauthorizedError("email 或密碼錯誤")

        logger.info("使用者登入成功 user_id=%s", user.id)
        return create_access_token(user.id)
