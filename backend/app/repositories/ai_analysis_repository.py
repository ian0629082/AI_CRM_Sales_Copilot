"""AI 分析紀錄的資料存取。

沒有 owner_id 過濾條件，因為它不對外提供查詢：
每一次讀取都是先從 Lead 進來（Lead 已經檢查過歸屬），再走 relationship 拿到分析紀錄。
"""

from sqlalchemy.orm import Session

from app.models.ai_analysis import AIAnalysis


class AIAnalysisRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, analysis: AIAnalysis) -> AIAnalysis:
        self.db.add(analysis)
        self.db.commit()
        self.db.refresh(analysis)
        return analysis

    def get_latest(self, lead_id: int, analysis_type: str) -> AIAnalysis | None:
        """這位客戶最近一次的某類分析。

        用 id 由大到小排而不是 created_at：同一秒內建立的兩筆
        （測試裡很常見）在 created_at 上分不出先後，而 id 一定分得出來。
        """
        return (
            self.db.query(AIAnalysis)
            .filter(
                AIAnalysis.lead_id == lead_id,
                AIAnalysis.analysis_type == analysis_type,
            )
            .order_by(AIAnalysis.id.desc())
            .first()
        )
