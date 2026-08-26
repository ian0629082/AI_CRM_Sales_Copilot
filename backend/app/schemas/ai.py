"""AI 解析相關的資料契約。

`ParsedRequirement` 是整個 Sprint 3 的核心：它是模型輸出進入系統的唯一入口。

有人會問：既然 OpenAI 的 strict schema 已經保證格式正確，為什麼還要 Pydantic 再驗一次？
因為兩者管的事不同 ——

- **strict schema 保證「結構正確」**：欄位齊全、型別對、enum 值在清單內。
- **Pydantic 保證「值合理」**：預算不能是負數、房數不能是 99、屋齡不能是 500 年。

strict 模式傳不了 minimum / maximum 這類數值約束，所以這第二道關卡不是多餘的。
模型偶爾會吐出格式完全合法但語意荒謬的數字，那一刻擋下來的就是這裡。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import PropertyType, Purpose

# 住宅預算的合理上限（10 億台幣）。
# 這道防線是在擋模型偶爾多打幾個零 —— 「2000 萬」寫成 200 億這種錯誤，
# 格式上完全合法，只有數值範圍檢查抓得到。
MAX_BUDGET = 1_000_000_000


class ParsedRequirement(BaseModel):
    """AI 從客戶原話抽取出的結構化需求。

    每個欄位都可以是 None，而且 None 有明確意義：**客戶沒提到**。
    這是刻意的設計。抽取規則裡最重要的兩條原則是「不推算」與「不補全」：
    客戶說「不急」，purchase_timeline 就是 None，不能猜成 6 個月。
    """

    location: str | None = Field(
        default=None, max_length=100, description="客戶提到的區域，保留原話"
    )
    budget_min: int | None = Field(default=None, ge=0, le=MAX_BUDGET)
    budget_max: int | None = Field(default=None, ge=0, le=MAX_BUDGET)
    budget_is_approximate: bool = Field(
        default=False, description="客戶說的是概數（2000 萬左右）還是精確數字"
    )
    rooms: int | None = Field(default=None, ge=0, le=20)
    property_type: PropertyType | None = None
    building_age_max: int | None = Field(
        default=None, ge=0, le=100, description="可接受的屋齡上限（年）"
    )
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

    @model_validator(mode="after")
    def approximate_needs_a_budget(self):
        """沒有任何預算數字，卻標記成「概數」是矛盾的。

        會擋這個，是因為 budget_is_approximate 在 Sprint 5 的 Lead Scoring
        要用來分辨「預算明確」與「還在觀望」。若它可以在沒有預算時被設為 true，
        那筆客戶的分數就會莫名其妙地少 15 分，而且很難查出原因。
        """
        if self.budget_is_approximate and self.budget_max is None and self.budget_min is None:
            raise ValueError("沒有預算數字時，budget_is_approximate 不應為 true")
        return self


class AIAnalysisRead(BaseModel):
    """一次 AI 分析的紀錄，回給前端用來顯示「AI 解析」徽章與分析時間。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    analysis_type: str
    # 資料庫裡存的是 JSON，這裡宣告成 ParsedRequirement 而不是 dict：
    # OpenAPI 才會描述出實際的欄位，前端生成的型別也才有內容可以用
    # （dict 會被生成成 Record<string, never>，等於什麼都拿不到）。
    parsed_result: ParsedRequirement | None
    prompt_version: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int | None
    created_at: datetime


