"""FastAPI 應用程式進入點。

這個檔案只負責「組裝」：建立 app、掛上中介層、掛上路由、註冊錯誤處理。
任何商業邏輯都不應該出現在這裡。
"""

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import auth, interactions, leads
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import setup_logging
from app.core.middleware import (
    REQUEST_ID_HEADER,
    RequestContextMiddleware,
    build_error_response,
)

setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="0.1.0",
    description="AI 驅動的房仲業務 CRM 助手",
)

# --- 中介層 ---
#
# Starlette 的中介層是「後掛的在外層」，所以下面兩行的順序決定了
# 執行順序是：CORS → RequestContext → 路由。
#
# 這個順序是刻意的。RequestContextMiddleware 會把未預期的例外就地變成 500，
# 那個回應必須再經過外層的 CORS 才會被加上 CORS header ——
# 少了它，瀏覽器會整包擋掉，前端只看得到一個沒有內容的網路錯誤，
# 連我們特地放進回應裡的 request_id 都讀不到。
#
# 代價是被 CORS 擋掉的 preflight 不會留下請求 log。這個取捨划算：
# preflight 被擋是開發期一看就知道的問題，
# 而正式環境的 500 追查不到，是使用者遇到了、我們卻無從查起。
app.add_middleware(RequestContextMiddleware)

# 前端跟後端不同來源（開發時是不同 port，上線後是不同網域），
# 瀏覽器會擋跨來源請求，所以要開 CORS。允許的網址由環境變數決定。
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # 瀏覽器預設只讓 JavaScript 讀得到少數幾個回應 header，
    # 不明講的話前端拿不到 request id，也就沒辦法顯示給使用者。
    expose_headers=[REQUEST_ID_HEADER],
)


@app.exception_handler(AppError)
def handle_app_error(request: Request, exc: AppError):
    """把領域錯誤翻譯成 HTTP 回應，讓 Service 層不必知道 HTTP。"""
    logger.warning("AppError on %s %s: %s", request.method, request.url.path, exc.message)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.exception_handler(Exception)
def handle_unexpected_error(request: Request, exc: Exception):
    """最後一道防線：連 RequestContextMiddleware 都沒接住的例外。

    正常情況下這裡永遠不會被觸發 —— 未預期的例外在 middleware 就會被
    攔下來變成 500（那個位置才進得了 CORS）。
    但如果是 middleware 自己壞掉，就只剩這裡了，
    而「錯誤處理本身壞掉時把堆疊裸露給使用者」是最不該發生的事。
    """
    return build_error_response(request, exc)


app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(leads.router, prefix=settings.API_V1_PREFIX)
app.include_router(interactions.router, prefix=settings.API_V1_PREFIX)


@app.get("/health", tags=["system"])
def health_check():
    return {"status": "ok"}
