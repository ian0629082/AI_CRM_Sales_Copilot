"""Lead 的 API 資料契約（Phase 4 API Contract 的程式碼版本）。

Schema 與 Model 刻意分開：
- Model 是資料庫長什麼樣
- Schema 是 API 對外承諾長什麼樣
兩者分開，日後改資料庫欄位才不會直接破壞前端。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.models.enums import LeadLevel, LeadSource, LeadStatus, Purpose
from app.schemas.interaction import InteractionRead


class LeadRequirementFields(BaseModel):
    """AI 解析後的結構化需求。Sprint 3 的 LLM Structured Output 也會沿用這組欄位。"""

    location: str | None = Field(default=None, max_length=100)
    budget_min: int | None = Field(default=None, ge=0)
    budget_max: int | None = Field(default=None, ge=0)
    rooms: int | None = Field(default=None, ge=0, le=20)
    parking: bool | None = None
    purpose: Purpose | None = None
    purchase_timeline: int | None = Field(
        default=None, ge=0, le=120, description="預計幾個月內購買"
    )

    @model_validator(mode="after")
    def check_budget_range(self):
        if (
            self.budget_min is not None
            and self.budget_max is not None
            and self.budget_min > self.budget_max
        ):
            raise ValueError("budget_min 不可以大於 budget_max")
        return self


class LeadCreate(LeadRequirementFields):
    name: str = Field(min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=50)
    email: EmailStr | None = None
    source: LeadSource = LeadSource.OTHER
    raw_requirement: str | None = None


class LeadUpdate(BaseModel):
    """PATCH 用。所有欄位都是選填，只更新有帶的欄位。"""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=50)
    email: EmailStr | None = None
    source: LeadSource | None = None
    status: LeadStatus | None = None
    raw_requirement: str | None = None

    location: str | None = Field(default=None, max_length=100)
    budget_min: int | None = Field(default=None, ge=0)
    budget_max: int | None = Field(default=None, ge=0)
    rooms: int | None = Field(default=None, ge=0, le=20)
    parking: bool | None = None
    purpose: Purpose | None = None
    purchase_timeline: int | None = Field(default=None, ge=0, le=120)


class LeadRead(BaseModel):
    """回傳給前端的完整 Lead。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    phone: str | None
    email: str | None
    source: LeadSource
    status: LeadStatus
    raw_requirement: str | None

    location: str | None
    budget_min: int | None
    budget_max: int | None
    rooms: int | None
    parking: bool | None
    purpose: Purpose | None
    purchase_timeline: int | None

    lead_score: int | None
    lead_level: LeadLevel | None

    owner_id: int | None
    created_at: datetime
    updated_at: datetime


class LeadListResponse(BaseModel):
    """列表一律包一層，日後要加 total / page 才不用改前端的解析方式。"""

    items: list[LeadRead]
    total: int


class LeadDetail(LeadRead):
    """Lead Detail 頁專用：在基本資料之外，一併帶出互動紀錄 Timeline。

    列表用 LeadRead（輕量），詳細頁用 LeadDetail（含 interactions），
    這樣列表 50 筆客戶時不會順便把幾百筆互動紀錄一起撈出來。
    """

    interactions: list[InteractionRead] = []
