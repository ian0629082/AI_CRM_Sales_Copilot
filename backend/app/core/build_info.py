"""線上跑的是哪一版。

## 為什麼需要

部署平台的設定（要跟著哪個分支）只有登入那個平台的人看得到，
而「我以為它跟著 main」與「它其實跟著別的分支」在外面長得一模一樣 ——
兩個分支指向同一份程式碼的時候完全分辨不出來，
等到程式碼真的分岔了才會發現，那時症狀是「改好的東西沒有上線」。

所以讓服務自己說。這也是查問題時很常需要的第一個問題：
「線上現在到底跑著哪一版？」

## 來源

Render 在建置與執行時都會注入這幾個環境變數，不必自己設。
其他平台（或本機）沒有這些變數，就回 None ——
**不要用「unknown」之類的字串填空**，那會讓「沒有這個資訊」
跟「這個資訊的值是 unknown」變成同一件事。
"""

import os

from pydantic import BaseModel


class BuildInfo(BaseModel):
    """這個服務是從哪個 commit 建出來的。

    branch 是最常看的那個欄位：部署平台設定改了沒、有沒有生效，
    看它就知道。
    """

    branch: str | None = None
    commit: str | None = None
    # 部署平台自己給的服務名稱，同一個帳號跑多個環境時用得上
    service: str | None = None


def current_build() -> BuildInfo:
    """每次呼叫都重讀環境變數。

    不快取成模組層級的常數：那樣測試要換值就得重新載入模組，
    而這個函式一天被呼叫不到幾次，省下來的那點時間沒有意義。
    """
    return BuildInfo(
        branch=os.environ.get("RENDER_GIT_BRANCH") or None,
        # commit 取前 7 碼就夠對照了，完整的 40 碼只是佔位置
        commit=(os.environ.get("RENDER_GIT_COMMIT") or "")[:7] or None,
        service=os.environ.get("RENDER_SERVICE_NAME") or None,
    )
