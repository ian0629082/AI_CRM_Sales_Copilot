"""註冊、登入與查詢自己的帳號資訊。"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.user import Token, UserCreate, UserLogin, UserRead
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


def get_auth_service(db: Session = Depends(get_db)) -> AuthService:
    return AuthService(db)


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(
    payload: UserCreate,
    service: AuthService = Depends(get_auth_service),
):
    """註冊新的業務帳號。回傳使用者資料，不含密碼雜湊。"""
    return service.register(payload)


@router.post("/login", response_model=Token)
def login(
    payload: UserLogin,
    service: AuthService = Depends(get_auth_service),
):
    """登入並取得 access token。"""
    return Token(access_token=service.login(payload))


@router.get("/me", response_model=UserRead)
def read_current_user(current_user: User = Depends(get_current_user)):
    """回傳目前登入者的資料。前端可用它確認 token 是否還有效。"""
    return current_user
