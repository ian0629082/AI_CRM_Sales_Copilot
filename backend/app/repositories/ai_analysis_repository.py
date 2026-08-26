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
