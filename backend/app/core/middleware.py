"""HTTP 中介層。

目前只有一個：替每個請求建立脈絡（request_id、來源 IP），
並在請求結束時記一行「誰、打了什麼、拿到幾號、花多久」。
"""

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.logging import get_request_id, new_request_id, set_request_context

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"

# 對外一律只說這一句。細節留在 log 裡。
UNEXPECTED_ERROR_MESSAGE = "伺服器發生非預期的錯誤，請稍後再試"


def forwarded_chain(request: Request) -> list[str]:
    """X-Forwarded-For 拆成一串，最左邊是最早的那一段。"""
    raw = request.headers.get("X-Forwarded-For", "")
    return [part.strip() for part in raw.split(",") if part.strip()]


def claimed_client_ip(request: Request) -> str:
    """客戶端**宣稱**的來源 IP（X-Forwarded-For 的第一段）。

    這個值是送請求的人自己填的，實測過 Render 不會覆蓋它 ——
    偽造 `X-Forwarded-For: 1.2.3.4` 之後，log 裡就是 1.2.3.4。

    所以它只能用來查問題與看趨勢，**不能當作封鎖或計數的依據**。
    用一個攻擊者控制得了的值當節流的鍵，跟沒有節流沒兩樣，
    差別只在你以為有 —— 他每送一次請求換一個假 IP，計數器永遠不會累積。
    """
    chain = forwarded_chain(request)
    if chain:
        return chain[0]
    return request.client.host if request.client else "-"


def trusted_client_ip(request: Request) -> str:
    """可以拿來計數的來源 IP：X-Forwarded-For 的**最後一段**。

    這串的規則是「每經過一層代理就往後面附加一個」，所以：

        X-Forwarded-For: 1.2.3.4, 61.223.40.235
                         ↑客戶端自己寫的  ↑Render 附加的

    客戶端能決定的只有前面那些，最後一段是我們前面那一層代理寫的 ——
    它是這串裡唯一不受外部控制的值。

    這個寫法**只在「前面剛好一層可信代理」時正確**。
    多一層或少一層都會取到錯的東西：少一層會拿到客戶端偽造的值，
    多一層會拿到內層代理的 IP（那樣所有人的 IP 都一樣，一鎖就鎖全部）。
    所以這件事不能靠猜，要在實際環境上驗證過 —— 驗證方式見下面那行 log。

    沒有這個 header 時（本機開發、直連）退回 TCP 的對端位址。
    """
    chain = forwarded_chain(request)
    if chain:
        return chain[-1]
    return request.client.host if request.client else "-"


def build_error_response(
    request: Request, exc: Exception, request_id: str | None = None
) -> JSONResponse:
    """把沒有被預期到的例外變成一個安全的 500 回應，並把細節寫進 log。

    這裡同時解決兩個方向相反的問題：

    **對外要少說。** 預設的錯誤畫面可能把堆疊、檔案路徑、套件版本、
    甚至 SQL 語句吐給呼叫端，那些正是攻擊者最想看的東西。
    所以對外只回一句固定的話，加上一組可以拿來追查的代碼。

    **對內要說完。** 正式環境沒有終端機可以看，
    堆疊如果沒有主動寫進 log 就等於不存在。

    回 500 是誠實的：它代表「我們的程式壞了」，
    與 AIServiceError 的 503（外部服務暫時不可用，等一下再試）意思不同。
    """
    request_id = request_id or getattr(request.state, "request_id", None) or get_request_id()

    # 用 exc_info=exc 明確指定，而不是 logger.exception()。
    # 後者靠 sys.exc_info() 抓「當下的例外」，但同步的錯誤處理器會被丟到
    # threadpool 執行，換了執行緒之後那個當下就是空的 ——
    # log 只會留下一句 "NoneType: None"，剛好把最需要的 traceback 弄丟。
    logger.error(
        "未處理的例外 on %s %s (request_id=%s)",
        request.method,
        request.url.path,
        request_id,
        exc_info=exc,
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": UNEXPECTED_ERROR_MESSAGE,
            # 把 id 一起回給前端，使用者截圖回報時我們才查得到是哪一次請求。
            "request_id": request_id,
        },
        headers={REQUEST_ID_HEADER: request_id},
    )


class RequestContextMiddleware(BaseHTTPMiddleware):
    """替每個請求綁定 request_id，並把它回寫到回應的 header。

    回寫是關鍵的一半：使用者遇到錯誤時，畫面上顯示的那組代碼就是這個 id，
    他截圖給你，你直接拿去搜 log 就能看到那一次請求的完整經過。
    沒有回寫的話，這個 id 只有伺服器自己知道，等於白做。
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # 若前面的閘道已經給過 id 就沿用，這樣跨服務追查時是同一條線。
        # 但長度要設限：這個值會進 log，不能讓外部塞一大段字進來洗版。
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = incoming[:64] if incoming else new_request_id()

        set_request_context(request_id, trusted_client_ip(request))
        request.state.request_id = request_id

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            # 兜底處理放在這裡，而不是用 @app.exception_handler(Exception)。
            #
            # 理由是 CORS：Starlette 內建的錯誤處理器位在整個中介層堆疊的最外面，
            # 它產生的回應不會經過 CORSMiddleware，所以那個 500 沒有 CORS header。
            # 瀏覽器會因此直接擋掉整個回應 —— 前端拿到的是一個沒有內容的網路錯誤，
            # 連我們特地放進去的 request_id 都讀不到，追查用的那條線就斷了。
            #
            # 從這一層回應，回應會照正常路徑往外經過 CORS，header 才補得上。
            response = build_error_response(request, exc, request_id)

        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers[REQUEST_ID_HEADER] = request_id

        # ip 是拿來計數的那個（最後一段），hops 是這串總共有幾段。
        #
        # hops 看起來是多餘的，但它是驗證「取最後一段對不對」的唯一依據：
        # 正式環境的每個請求都應該固定是 1（Render 那一層）。
        # 哪天平台在前面多加一層，hops 會變成 2，而那時候 ip 取到的
        # 就不再是客戶端 —— 沒有這個數字的話，症狀會是
        # 「節流突然把所有人一起鎖住」，而且完全看不出原因。
        trusted = trusted_client_ip(request)
        hops = len(forwarded_chain(request))
        logger.info(
            "%s %s → %s (%.0f ms) ip=%s hops=%s",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            trusted,
            hops,
        )
        return response
