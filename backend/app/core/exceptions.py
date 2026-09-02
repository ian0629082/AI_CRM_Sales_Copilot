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


class ConflictError(AppError):
    status_code = 409
    message = "資料衝突"


class UnauthorizedError(AppError):
    status_code = 401
    message = "身分驗證失敗"


class ForbiddenError(AppError):
    status_code = 403
    message = "沒有權限執行此操作"


class ValidationError(AppError):
    """輸入不符合商業規則（例如要分析卻沒有客戶原話）。"""

    status_code = 422
    message = "資料不符合要求"


class RateLimitError(AppError):
    """超過使用次數上限。

    429 而不是 403：403 是「你沒有權限做這件事」，
    429 是「你有權限，只是現在太多了，等一下就可以」——
    前端要據此決定顯示「請聯絡管理員」還是「明天再試」。

    訊息要講清楚上限是多少、什麼時候恢復。只說「已達上限」的話，
    使用者不知道該等一分鐘還是等到明天，那種不確定比限制本身更難受。
    """

    status_code = 429
    message = "已達使用上限，請稍後再試"


class AIServiceError(AppError):
    """AI 分析失敗。

    刻意用 503 而不是 500：這代表「外部服務暫時不可用，等一下再試」，
    而不是「我們的程式壞了」。前端可以據此顯示重試按鈕。

    最重要的是，這個錯誤絕不能牽連 CRM 本身 —— AI 掛掉時，
    客戶資料的增刪改查、互動紀錄、登入都必須照常運作。
    """

    status_code = 503
    message = "AI 分析目前無法完成，請稍後再試"
