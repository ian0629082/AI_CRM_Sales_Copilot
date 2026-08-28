"""日誌設定與請求脈絡。

這個檔案回答的問題不是「怎麼把訊息印出來」，而是
**「出事之後，怎麼把散落在各層的那幾行 log 拼回同一次請求」**。

正式環境沒有終端機可以看。使用者只會說「我剛剛按 AI 解析壞掉了」，
而 Render 的 log 面板上是幾百行來自不同人、不同請求、交錯在一起的訊息。
沒有一個共同的識別碼，那些行就只是一堆孤立的句子。

做法是一個 contextvar：middleware 在請求進來時產生 request_id，
之後同一個請求裡的每一行 log 都會自動帶上它，Service 層完全不必知道這件事。
"""

import logging
import uuid
from contextvars import ContextVar

# contextvar 而不是 thread local：FastAPI 同時有 async route（跑在事件迴圈）
# 與 def route（被丟到 threadpool），thread local 在前者會整批共用同一個值。
# contextvar 兩種情況都正確，asyncio 與 threadpool 都會各自複製一份 context。
_request_id: ContextVar[str] = ContextVar("request_id", default="-")
_client_ip: ContextVar[str] = ContextVar("client_ip", default="-")

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(request_id)s | %(name)s | %(message)s"


def new_request_id() -> str:
    """產生一個短的請求識別碼。

    只取 uuid4 的前 8 碼：完整的 36 字元會把每一行 log 撐得很長，
    而它要對抗的不是全世界的碰撞，只是「同一份 log 裡同時存在的那幾千個請求」。
    """
    return uuid.uuid4().hex[:8]


def set_request_context(request_id: str, client_ip: str) -> None:
    _request_id.set(request_id)
    _client_ip.set(client_ip)


def get_request_id() -> str:
    return _request_id.get()


def get_client_ip() -> str:
    return _client_ip.get()


class RequestContextFilter(logging.Filter):
    """把 request_id 塞進每一筆 LogRecord。

    用 Filter 而不是要求每個呼叫端自己帶：
    一旦需要「每次都記得寫」，就一定會有地方漏掉，
    而漏掉的那一行往往正是出事時最想看的那一行。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # 沒有 request context 的情況（啟動階段、背景腳本）會拿到預設的 "-"，
        # 不能讓它變成 KeyError 把整個 log 打掛。
        record.request_id = _request_id.get()
        return True


def setup_logging(level: int = logging.INFO) -> None:
    """設定 root logger。應用程式啟動時呼叫一次。

    刻意只往 stdout 印，不寫檔案、不接第三方服務：
    Render、Docker、GitHub Actions 都會自動收集 stdout，
    自己管理 log 檔案在這種環境反而是多餘的一層。
    """
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    handler.addFilter(RequestContextFilter())

    root = logging.getLogger()
    # 重複呼叫（例如測試多次載入）不要疊加 handler，否則同一行會印很多次
    for existing in root.handlers[:]:
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)


def mask_email(email: str) -> str:
    """把 email 遮成 `ab***@example.com`，給 log 用。

    為什麼不直接寫完整的 email：log 的可見範圍比資料庫大得多 ——
    它會出現在雲端平台的網頁面板、CI 的輸出、你卡關時貼給別人看的截圖裡。
    而「登入失敗」的 log 累積起來，本質上就是一份有人試過的帳號清單。

    為什麼不乾脆完全不記：遮罩後同一個帳號的多次失敗仍然長得一樣，
    「有人針對這個帳號反覆嘗試」照樣看得出來，這是查問題真正需要的資訊。
    """
    if not email:
        return "-"
    local, sep, domain = email.partition("@")
    if not sep:
        # 不是 email 格式（使用者亂填）就整串遮掉，不去猜它是什麼
        return f"{local[:2]}***" if local else "-"
    return f"{local[:2]}***@{domain}"
