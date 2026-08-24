"""Repository：只負責跟資料庫講話，不做任何商業判斷。

好處是 Sprint 6 寫測試時，可以只針對 Service 測商業邏輯，
不需要每次都真的連資料庫。
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.enums import LeadStatus
from app.models.lead import Lead


class LeadRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, lead: Lead) -> Lead:
        self.db.add(lead)
        self.db.commit()
        self.db.refresh(lead)
        return lead

    def get(self, lead_id: int) -> Lead | None:
        return self.db.get(Lead, lead_id)

    def get_with_interactions(self, lead_id: int) -> Lead | None:
        stmt = (
            select(Lead)
            .where(Lead.id == lead_id)
            .options(selectinload(Lead.interactions))
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list(
        self,
        *,
        status: LeadStatus | None = None,
        keyword: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[Lead], int]:
        stmt = select(Lead)
        if status is not None:
            stmt = stmt.where(Lead.status == status)
        if keyword:
            pattern = f"%{keyword}%"
            stmt = stmt.where(Lead.name.ilike(pattern) | Lead.phone.ilike(pattern))

        total = self.db.execute(
            select(func.count()).select_from(stmt.subquery())
        ).scalar_one()

        # 未評分的 Lead 排在最後，其餘依分數由高到低 —— 對應「今天該先聯絡誰」
        stmt = stmt.order_by(Lead.lead_score.desc().nullslast(), Lead.created_at.desc())
        items = list(self.db.execute(stmt.offset(skip).limit(limit)).scalars())
        return items, total

    def save(self, lead: Lead) -> Lead:
        self.db.commit()
        self.db.refresh(lead)
        return lead

    def delete(self, lead: Lead) -> None:
        self.db.delete(lead)
        self.db.commit()
