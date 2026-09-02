"""跟「當地的一天」有關的時間換算。

伺服器跑在 UTC，使用者在台灣。這兩件事只要碰到「每天」就會打架 ——
照 UTC 算日界線的話，額度會在台灣時間早上八點重置，
業務早上進辦公室按了幾次，額度就莫名其妙跳掉了。

所以「今天」一律以 settings.LOCAL_TIMEZONE 為準，
只有在跟資料庫比對時才換回 UTC。
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.core.config import settings


def local_day_start_utc(now: datetime | None = None) -> datetime:
    """回傳「當地今天的 00:00」對應的 UTC 時間（aware）。

    拿來當資料庫查詢的下界：`created_at >= local_day_start_utc()`。

    `now` 可以傳入，測試才不必依賴真實時鐘 ——
    一個會隨著執行時間變綠變紅的測試，遲早會被當成雜訊忽略掉。
    """
    tz = ZoneInfo(settings.LOCAL_TIMEZONE)
    current = (now or datetime.now(UTC)).astimezone(tz)
    day_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    return day_start.astimezone(UTC)
