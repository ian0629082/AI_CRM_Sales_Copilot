from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.models.enums import LeadLevel, LeadSource, LeadStatus, Purpose


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
    rooms: Mapped[int | None] = mapped_column(Integer)
    parking: Mapped[bool | None] = mapped_column(Boolean)
    purpose: Mapped[Purpose | None] = mapped_column(
        SAEnum(Purpose, native_enum=False, length=20)
    )
    purchase_timeline: Mapped[int | None] = mapped_column(
        Integer, comment="預計幾個月內購買"
    )

    # --- Rule Engine 計算（Sprint 5）---
    lead_score: Mapped[int | None] = mapped_column(Integer, index=True)
    lead_level: Mapped[LeadLevel | None] = mapped_column(
        SAEnum(LeadLevel, native_enum=False, length=10)
    )

    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped["User | None"] = relationship(back_populates="leads")  # noqa: F821
    interactions: Mapped[list["Interaction"]] = relationship(  # noqa: F821
        back_populates="lead",
        cascade="all, delete-orphan",
        # 同一秒內建立的紀錄，用 id 當第二排序鍵，確保 Timeline 順序穩定
        order_by="(Interaction.created_at.desc(), Interaction.id.desc())",
    )
