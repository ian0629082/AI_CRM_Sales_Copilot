"""API 層共用的 dependency。

get_current_user 是整個授權機制的入口：
任何需要登入才能用的 API，只要加上 Depends(get_current_user) 即可。
"""

import logging
from functools import lru_cache

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import UnauthorizedError
from app.core.security import decode_access_token
from app.db.database import get_db
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.services.ai_service import AIService
from app.services.follow_up_advisor import FollowUpAdvisor
from app.services.llm_provider import LLMError, OpenAIProvider

logger = logging.getLogger(__name__)

# auto_error=False：由我們自己丟 UnauthorizedError，
# 讓所有錯誤回應都經過 main.py 的 handler，維持一致的 {"detail": ...} 格式。
bearer_scheme = HTTPBearer(auto_error=False, description="貼上登入取得的 access_token")


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """從 Authorization: Bearer <token> 取出目前登入的使用者。"""
    if credentials is None:
        raise UnauthorizedError("請先登入")

    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise UnauthorizedError("Token 無效或已過期")

    user_id = payload.get("sub")
    if user_id is None:
        raise UnauthorizedError("Token 內容不完整")

    # token 有效不代表帳號還在：使用者可能已被刪除，所以仍要查一次資料庫
    user = UserRepository(db).get(int(user_id))
    if user is None:
        raise UnauthorizedError("使用者不存在")

    return user


@lru_cache(maxsize=1)
def get_llm_provider() -> OpenAIProvider | None:
    """建立 LLM provider，沒有設定 API key 時回傳 None。

    用 lru_cache 快取：OpenAI client 內含 HTTP 連線池，
    每個請求都 new 一個會浪費掉連線重用，也拖慢每次呼叫。

    快取的是 provider 而不是各個 service，這樣 AIService 與 FollowUpAdvisor
    共用同一個連線池 —— 它們用的是同一個 OpenAI 帳號、同一台伺服器。

    回傳 None 而不是丟錯誤，是為了守住「AI 是 Enhancement」這條線 ——
    沒設 key 的環境（例如 CI）仍然要能跑起整個 CRM，只是那幾顆按鈕會回 503。
    """
    if not settings.OPENAI_API_KEY:
        logger.warning("未設定 OPENAI_API_KEY，AI 功能停用")
        return None

    try:
        return OpenAIProvider(
            api_key=settings.OPENAI_API_KEY,
            model=settings.OPENAI_MODEL,
            timeout=settings.OPENAI_TIMEOUT_SECONDS,
        )
    except LLMError:
        logger.exception("建立 OpenAI provider 失敗，AI 功能停用")
        return None


def get_ai_service() -> AIService | None:
    """需求解析（Sprint 3）。"""
    provider = get_llm_provider()
    return AIService(provider) if provider else None


def get_follow_up_advisor() -> FollowUpAdvisor | None:
    """跟進建議（Sprint 5）。

    跟 get_ai_service 分開成兩個 dependency，而不是塞成同一個「AI 服務」：
    兩者用的 prompt、schema、驗證方式都不一樣，
    而且日後很可能各自用不同的模型 —— 解析要便宜穩定，寫話術可以換好一點的。
    """
    provider = get_llm_provider()
    return FollowUpAdvisor(provider) if provider else None
