"""API 層共用的 dependency。

get_current_user 是整個授權機制的入口：
任何需要登入才能用的 API，只要加上 Depends(get_current_user) 即可。
"""

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.exceptions import UnauthorizedError
from app.core.security import decode_access_token
from app.db.database import get_db
from app.models.user import User
from app.repositories.user_repository import UserRepository

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
