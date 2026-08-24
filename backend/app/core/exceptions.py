"""領域層的錯誤。

Service 不應該知道 HTTP 是什麼，所以它丟這些錯誤，
再由 main.py 的 exception handler 統一翻譯成 HTTP 狀態碼。
"""


class AppError(Exception):
    """所有自訂錯誤的共同父類別。"""

    status_code = 400
    message = "發生錯誤"

    def __init__(self, message: str | None = None):
        self.message = message or self.message
        super().__init__(self.message)


class NotFoundError(AppError):
    status_code = 404
    message = "找不到資料"
