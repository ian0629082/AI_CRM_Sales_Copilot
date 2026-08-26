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

    # 明確關閉這位客戶的提醒（成交、流失、確定放棄）。
    # 與「不填 next_follow_up_days」不同：那是「用預設」，這是「不要提醒」。
    mute_follow_up: bool = False


class InteractionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lead_id: int
    type: InteractionType
    content: str
    created_at: datetime
