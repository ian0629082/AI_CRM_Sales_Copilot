"""Repository：只負責跟資料庫講話，不做任何商業判斷。

所有查詢都強制帶 owner_id 條件，把「只能看到自己的客戶」直接落在 SQL 層。
比起撈回來再用 Python 比對，這樣少一個漏檢的機會。
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

    def get_for_owner(self, lead_id: int, owner_id: int) -> Lead | None:
        stmt = select(Lead).where(Lead.id == lead_id, Lead.owner_id == owner_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_with_interactions(self, lead_id: int, owner_id: int) -> Lead | None:
        stmt = (
            select(Lead)
            .where(Lead.id == lead_id, Lead.owner_id == owner_id)
            .options(
                selectinload(Lead.interactions),
                selectinload(Lead.ai_analyses),
            )
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_for_follow_up(self, owner_id: int) -> list[Lead]:
        """撈出所有還沒結案的客戶，連同互動一起載入。

        用 selectinload 一次撈完 —— 判斷「有沒有被聯絡過」要看互動，
        逐筆去查會變成 N+1，而資料庫在新加坡，每一次來回都是幾十毫秒。
        """
        stmt = (
            select(Lead)
            .where(
                Lead.owner_id == owner_id,
                Lead.status.notin_([LeadStatus.WON, LeadStatus.LOST]),
            )
            .options(selectinload(Lead.interactions))
        )
        return list(self.db.execute(stmt).scalars())

    def list(
        self,
        *,
        owner_id: int,
        status: LeadStatus | None = None,
        keyword: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[Lead], int]:
        stmt = select(Lead).where(Lead.owner_id == owner_id)
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
