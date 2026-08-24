"""FastAPI 應用程式進入點。

這個檔案只負責「組裝」：建立 app、掛上中介層、掛上路由、註冊錯誤處理。
任何商業邏輯都不應該出現在這裡。
"""

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import interactions, leads
from app.core.config import settings
from app.core.exceptions import AppError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="0.1.0",
    description="AI 驅動的房仲業務 CRM 助手",
)

# 前端在 localhost:3000，跟後端不同 port，瀏覽器會擋跨來源請求，所以要開 CORS。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AppError)
def handle_app_error(request: Request, exc: AppError):
    """把領域錯誤翻譯成 HTTP 回應，讓 Service 層不必知道 HTTP。"""
    logger.warning("AppError on %s %s: %s", request.method, request.url.path, exc.message)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


app.include_router(leads.router, prefix=settings.API_V1_PREFIX)
app.include_router(interactions.router, prefix=settings.API_V1_PREFIX)


@app.get("/health", tags=["system"])
def health_check():
    return {"status": "ok"}
