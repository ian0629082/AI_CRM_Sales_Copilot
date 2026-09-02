"""AI 分析紀錄的資料存取。

一般的讀取沒有 owner_id 過濾條件，因為它不對外提供查詢：
每一次讀取都是先從 Lead 進來（Lead 已經檢查過歸屬），再走 relationship 拿到分析紀錄。

例外是 `count_since`：它要回答「這位業務今天用掉幾次」，
歸屬是問題本身的一部分，所以那一支才 join 到 leads.owner_id。
"""

from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.ai_analysis import AIAnalysis
from app.models.lead import Lead


class AIAnalysisRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, analysis: AIAnalysis) -> AIAnalysis:
        self.db.add(analysis)
        self.db.commit()
        self.db.refresh(analysis)
        return analysis

    def count_since(self, owner_id: int, analysis_type: str, since: datetime) -> int:
        """這位業務從 `since` 之後用掉幾次某類分析。

        用既有的 ai_analysis 表算，不另外開一張計數表：
        每一次分析本來就會留下一筆紀錄，再存一個計數等於同一件事記兩遍，
        而兩份紀錄一旦對不上，你不會知道該信哪一個。

        額外的好處是這個計數天生耐得住重啟 —— Render 免費方案會休眠，
        放在記憶體裡的計數一醒來就歸零，上限等於形同虛設。

        只算成功的次數：失敗不會留下紀錄，所以不佔額度。
        這跟「解析失敗不進快取、重試不會被擋」是同一條線 ——
        使用者不該為我們這邊的失敗付出代價。
        """
        total = (
            self.db.query(func.count(AIAnalysis.id))
            .join(Lead, Lead.id == AIAnalysis.lead_id)
            .filter(
                Lead.owner_id == owner_id,
                AIAnalysis.analysis_type == analysis_type,
                AIAnalysis.created_at >= since,
            )
            .scalar()
        )
        return total or 0

    def count_all_since(self, analysis_type: str, since: datetime) -> int:
        """全站從 `since` 之後總共用掉幾次某類分析。

        跟 count_since 的差別只有「不看是誰用的」。
        個人上限擋不住「很多人各用一點」，而帳單不管是誰按的。
        """
        total = (
            self.db.query(func.count(AIAnalysis.id))
            .filter(
                AIAnalysis.analysis_type == analysis_type,
                AIAnalysis.created_at >= since,
            )
            .scalar()
        )
        return total or 0

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
