from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base

# analysis_type 的兩個合法值。
#
# 定義成常數而不是各處寫字串，是因為它同時被三個地方用到：
# 寫入時（LeadService）、讀取時的過濾（Lead.latest_analysis）、
# 以及評估腳本。三個地方各寫一次字串，只要有一個打錯，
# 症狀會是「徽章莫名其妙消失」這種很難追的問題。
REQUIREMENT_PARSING = "REQUIREMENT_PARSING"
FOLLOW_UP = "FOLLOW_UP"


class AIAnalysis(Base):
    """每一次 AI 分析的完整紀錄。

    為什麼結果已經寫回 lead 欄位了，還要另外存一張表？

    1. **可追溯**：lead 上的欄位會被業務手動改掉，改完就再也看不出 AI 原本抽到什麼。
       這張表保留每次分析的原始輸出，是 Sprint 4 Evaluation 的資料來源。
    2. **可比較**：存了 prompt_version 與 model，Prompt 改版或換模型後，
       同一位客戶前後兩次的結果可以直接對照。
    3. **可算成本**：token 數與耗時留著，Sprint 4 才有辦法講「準確率 96%，每筆 0.002 美元」。

    欄位一次建齊（含 Sprint 5 的 Follow-up 建議），避免下個 Sprint 再跑一次 migration。
    """

    __tablename__ = "ai_analysis"

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), index=True
    )

    # REQUIREMENT_PARSING（Sprint 3）/ FOLLOW_UP（Sprint 5）
    analysis_type: Mapped[str] = mapped_column(String(30))

    # 分析當下餵給模型的原話快照。
    # 不直接看 lead.raw_requirement 是因為客戶原話之後可能被業務編輯，
    # 那樣就對不上這次的輸出了。
    input_text: Mapped[str] = mapped_column(Text)

    # --- Sprint 3：需求解析 ---
    # 模型回傳、通過驗證後的結構化結果，整包存 JSON。
    # 不拆成欄位是因為這裡要的是「當時輸出的快照」，不是拿來查詢的資料。
    parsed_result: Mapped[dict | None] = mapped_column(JSON)

    # --- Sprint 5：跟進建議 ---
    suggestion: Mapped[str | None] = mapped_column(Text)
    score_snapshot: Mapped[int | None] = mapped_column(Integer)
    level_snapshot: Mapped[str | None] = mapped_column(String(10))

    # --- 可重現性與成本 ---
    prompt_version: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(50))
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    lead: Mapped["Lead"] = relationship(back_populates="ai_analyses")  # noqa: F821
