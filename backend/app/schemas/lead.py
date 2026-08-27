"""Lead 的 API 資料契約（Phase 4 API Contract 的程式碼版本）。

Schema 與 Model 刻意分開：
- Model 是資料庫長什麼樣
- Schema 是 API 對外承諾長什麼樣
兩者分開，日後改資料庫欄位才不會直接破壞前端。
"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.models.enums import (
    LeadLevel,
    LeadSource,
    LeadStatus,
    PropertyType,
    Purpose,
    Urgency,
)
from app.schemas.ai import AIAnalysisRead, FollowUpAnalysisRead
from app.schemas.interaction import InteractionRead


class LeadRequirementFields(BaseModel):
    """AI 解析後的結構化需求。Sprint 3 的 LLM Structured Output 也會沿用這組欄位。"""

    location: str | None = Field(default=None, max_length=100)
    budget_min: int | None = Field(default=None, ge=0)
    budget_max: int | None = Field(default=None, ge=0)
    # budget_is_approximate 刻意不放在這裡（也就是新增客戶時不能填）。
    # 它回答的是「客戶說預算時的語氣」，這件事只有讀過原話才知道，
    # 由 AI 解析填入，或事後用 PATCH 修改。
    rooms: int | None = Field(default=None, ge=0, le=20)
    property_type: PropertyType | None = None
    building_age_max: int | None = Field(default=None, ge=0, le=100)
    parking: bool | None = None
    purpose: Purpose | None = None
    purchase_timeline: int | None = Field(
        default=None, ge=0, le=120, description="預計幾個月內購買"
    )
    urgency: Urgency | None = None

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
    budget_is_approximate: bool | None = None
    rooms: int | None = Field(default=None, ge=0, le=20)
    property_type: PropertyType | None = None
    building_age_max: int | None = Field(default=None, ge=0, le=100)
    parking: bool | None = None
    purpose: Purpose | None = None
    purchase_timeline: int | None = Field(default=None, ge=0, le=120)
    urgency: Urgency | None = None

    # 業務可以隨時直接改提醒日或關掉提醒，不必透過新增互動
    next_follow_up_at: date | None = None
    follow_up_muted: bool | None = None


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
    budget_is_approximate: bool
    rooms: int | None
    property_type: PropertyType | None
    building_age_max: int | None
    parking: bool | None
    purpose: Purpose | None
    purchase_timeline: int | None
    urgency: Urgency | None

    next_follow_up_at: date | None
    follow_up_muted: bool

    lead_score: int | None
    lead_level: LeadLevel | None

    owner_id: int
    created_at: datetime
    updated_at: datetime


class ScoreReasonRead(BaseModel):
    """一條計分理由。

    這些理由**不存資料庫**，每次讀取時重算。
    因為計分是確定性的規則，同樣的資料一定得到同樣的理由 ——
    存起來只會多一份可能過期的副本。
    """

    model_config = ConfigDict(from_attributes=True)

    code: str
    label: str
    points: int


class LeadListResponse(BaseModel):
    """列表一律包一層，日後要加 total / page 才不用改前端的解析方式。"""

    items: list[LeadRead]
    total: int


class FollowUpItem(BaseModel):
    """待跟進清單上的一列。"""

    lead: LeadRead
    bucket: str
    days_overdue: int
    reason: str


class FollowUpResponse(BaseModel):
    """待跟進清單，刻意分成兩堆而不是一份排序好的名單。

    「新進未聯絡」與「到期跟進」對應兩種不同的業務動作：
    一個是第一次接觸（搶時間），一個是維繫（別讓它冷掉）。
    混在一起的話，業務打開看到 20 個人，
    分不出哪些是還沒認識、哪些是快跑掉了。
    """

    new_uncontacted: list[FollowUpItem]
    due: list[FollowUpItem]
    # 業務主動關掉提醒的客戶數。
    # 只給數字不列名單：它不是待辦，但要讓業務知道自己關過幾個，
    # 不然某天會納悶「那個客戶怎麼再也沒出現過」。
    muted_count: int


class LeadDetail(LeadRead):
    """Lead Detail 頁專用：在基本資料之外，一併帶出互動紀錄 Timeline。

    列表用 LeadRead（輕量），詳細頁用 LeadDetail（含 interactions），
    這樣列表 50 筆客戶時不會順便把幾百筆互動紀錄一起撈出來。
    """

    interactions: list[InteractionRead] = []
    # 分數是怎麼來的，逐條列出。
    # 「可解釋」不是加分項，是這套 Scoring 敢拿來排序的前提 ——
    # 一個講不出理由的分數，沒有業務會照著它打電話。
    score_reasons: list[ScoreReasonRead] = []
    # 最近一次 AI 解析。前端靠它決定哪些欄位要掛「AI 解析」徽章，
    # 重新整理頁面後徽章也還在（不是只存在前端記憶體裡的狀態）。
    latest_analysis: AIAnalysisRead | None = None
    # 最近一則 AI 跟進建議。重新整理後仍然看得到，不必再花一次錢重產。
    latest_follow_up: FollowUpAnalysisRead | None = None


class LeadAnalyzeResponse(BaseModel):
    """POST /leads/{id}/analyze 的回應。

    一併回傳更新後的 lead，前端就不必再打一次 GET —— 少一次來回，
    也少一次「畫面上還是舊資料」的機會。
    """

    lead: LeadRead
    analysis: AIAnalysisRead


class LeadFollowUpResponse(BaseModel):
    """POST /leads/{id}/follow-up-suggestion 的回應。

    只回建議，不回 lead —— 因為產生建議不會改到客戶的任何欄位，
    前端手上那份資料仍然是對的，沒必要多傳一份回去。
    這跟 analyze 的回應刻意不一樣，差異本身就在說明兩支 API 的性質不同。
    """

    suggestion: FollowUpAnalysisRead
