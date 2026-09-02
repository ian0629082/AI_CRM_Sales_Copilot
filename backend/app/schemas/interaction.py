from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import InteractionType


class InteractionCreate(BaseModel):
    type: InteractionType
    content: str = Field(min_length=1)

    # 幾天後再提醒聯絡這位客戶。
    #
    # 不傳的話用系統依互動類型給的預設值（見 services/follow_up.py），
    # 傳 0 代表明天，傳 None 走預設。
    # 業務知道的比規則多 —— 客戶說「我下週三再回你」，填 7 就對了。
    next_follow_up_days: int | None = Field(default=None, ge=0, le=365)

    # 這次談定的帶看時間。
    #
    # 放在「記錄互動」這裡而不是另外一個頁面，是因為帶看幾乎都是在
    # 通話或 LINE 裡敲定的 —— 業務寫完「客戶說週六下午可以去看七期那間」，
    # 順手就把時間填了。多開一個地方要點，就多一個忘記填的理由，
    # 而這個欄位沒填的代價是白跑一趟。
    #
    # 不帶這個欄位代表「這次沒談到帶看」，不會動到原本已經約好的時間。
    # 要改期或取消請用 PATCH /leads/{id}。
    viewing_scheduled_at: datetime | None = None

    # 明確關閉這位客戶的提醒（成交、流失、確定放棄）。
    # 與「不填 next_follow_up_days」不同：那是「用預設」，這是「不要提醒」。
    #
    # 用 bool | None 而不是預設 False，是因為帶 default 的欄位在
    # OpenAPI 上仍會被標成必填，前端生成的型別就會逼每一次呼叫都帶這個旗標。
    # None 表示「沒有意見」，跟不帶這個欄位是同一件事。
    mute_follow_up: bool | None = None


class InteractionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lead_id: int
    type: InteractionType
    content: str
    created_at: datetime
