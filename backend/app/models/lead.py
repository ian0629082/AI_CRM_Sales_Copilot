from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    Text,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.models.ai_analysis import FOLLOW_UP, REQUIREMENT_PARSING
from app.models.enums import (
    LeadLevel,
    LeadSource,
    LeadStatus,
    PropertyType,
    Purpose,
    Urgency,
)


class Lead(Base):
    """潛在客戶。

    欄位分成三群，這個分群是整個專案的設計核心：

    1. 業務手動輸入      —— name / phone / email / source / status
    2. AI 從自然語言解析 —— location / budget / rooms / parking / purpose / timeline
    3. Rule Engine 計算  —— lead_score / lead_level

    raw_requirement 永遠保留客戶的原話，這樣 Prompt 改版後可以重跑並比較結果。
    """

    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(primary_key=True)

    # --- 業務手動輸入 ---
    name: Mapped[str] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(255))
    source: Mapped[LeadSource] = mapped_column(
        SAEnum(LeadSource, native_enum=False, length=20), default=LeadSource.OTHER
    )
    status: Mapped[LeadStatus] = mapped_column(
        SAEnum(LeadStatus, native_enum=False, length=20),
        default=LeadStatus.NEW,
        index=True,
    )

    # 客戶的原始自然語言需求，AI 解析的輸入來源
    raw_requirement: Mapped[str | None] = mapped_column(Text)

    # --- AI 解析後的結構化需求（Sprint 3 才會自動填，Sprint 1 可手動填）---
    location: Mapped[str | None] = mapped_column(String(100))
    budget_min: Mapped[int | None] = mapped_column(BigInteger)
    budget_max: Mapped[int | None] = mapped_column(BigInteger)
    # 客戶說的是「2000 萬左右」還是「就是 2000 萬」。
    # 搜尋時的 5% 緩衝由 Rule Engine 依這個旗標決定要不要加，
    # 而不是讓 AI 直接吐一個算好的數字 —— 否則這兩種語意在資料庫裡就分不出來了。
    budget_is_approximate: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    rooms: Mapped[int | None] = mapped_column(Integer)
    property_type: Mapped[PropertyType | None] = mapped_column(
        SAEnum(PropertyType, native_enum=False, length=20)
    )
    building_age_max: Mapped[int | None] = mapped_column(
        Integer, comment="可接受的屋齡上限（年）"
    )
    parking: Mapped[bool | None] = mapped_column(Boolean)
    purpose: Mapped[Purpose | None] = mapped_column(
        SAEnum(Purpose, native_enum=False, length=20)
    )
    purchase_timeline: Mapped[int | None] = mapped_column(
        Integer, comment="預計幾個月內購買"
    )
    # 客戶表達出的急迫程度。真實客戶很少講明確月數，卻常常講「有點急」，
    # 少了這一欄，那種客戶在 Lead Score 上會被當成沒有時間壓力。
    urgency: Mapped[Urgency | None] = mapped_column(
        SAEnum(Urgency, native_enum=False, length=10)
    )

    # --- 跟進提醒（Sprint 5）---
    # 下次該聯絡的日期，由業務在記錄互動時決定，系統只提供預設值。
    # 一度想寫一整張「什麼階段隔幾天」的規則表，後來拿掉了：
    # 客戶掛電話前說「我下週三再回你」，業務填 7 天就對了，規則猜不到那句話。
    next_follow_up_at: Mapped[date | None] = mapped_column(Date, index=True)

    # 業務明確關掉提醒（成交、流失、確定放棄）。
    # 與 next_follow_up_at 為 NULL 分開表示：NULL 是「還沒設」，
    # 這個是「刻意不要」。兩者混在一起的話，就分不出「漏設」與「不用設」。
    follow_up_muted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )

    # --- Rule Engine 計算（Sprint 5）---
    lead_score: Mapped[int | None] = mapped_column(Integer, index=True)
    lead_level: Mapped[LeadLevel | None] = mapped_column(
        SAEnum(LeadLevel, native_enum=False, length=10)
    )

    # 必填：每筆客戶都必須有歸屬的業務。
    # 加索引是因為每一次查詢都會用 owner_id 過濾（資料隔離）。
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped["User"] = relationship(back_populates="leads")  # noqa: F821
    interactions: Mapped[list["Interaction"]] = relationship(  # noqa: F821
        back_populates="lead",
        cascade="all, delete-orphan",
        # 同一秒內建立的紀錄，用 id 當第二排序鍵，確保 Timeline 順序穩定
        order_by="(Interaction.created_at.desc(), Interaction.id.desc())",
    )
    ai_analyses: Mapped[list["AIAnalysis"]] = relationship(  # noqa: F821
        back_populates="lead",
        cascade="all, delete-orphan",
        order_by="AIAnalysis.id.desc()",
    )

    def _latest_of(self, analysis_type: str):
        """ai_analyses 已由新到舊排序，取第一筆符合類型的即可。

        **一定要過濾 analysis_type。**
        這張表同時存需求解析與跟進建議兩種紀錄，
        不過濾的話，業務按一次「AI 跟進建議」之後，
        欄位上的「AI 解析」徽章就會全部消失 —— 因為最新那一筆變成了建議，
        它的 parsed_result 是 null，比對不到任何欄位。

        放在 model 上而不是 service 裡：這是「Lead 這個東西本身的性質」，
        每個需要它的地方（API、日後的 n8n、Agent）都能直接用，不必各自再寫一次。
        """
        return next((a for a in self.ai_analyses if a.analysis_type == analysis_type), None)

    @property
    def latest_analysis(self):
        """最近一次需求解析。前端靠它決定哪些欄位要掛「AI 解析」徽章。"""
        return self._latest_of(REQUIREMENT_PARSING)

    @property
    def latest_follow_up(self):
        """最近一次跟進建議。"""
        return self._latest_of(FOLLOW_UP)
