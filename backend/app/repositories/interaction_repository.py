"""Interaction 的資料庫存取層。

跟 LeadRepository 一樣，這裡不做任何商業判斷，
「這個 Lead 存不存在」之類的檢查是 Service 的責任。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.interaction import Interaction


class InteractionRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, interaction: Interaction) -> Interaction:
        self.db.add(interaction)
        self.db.commit()
        self.db.refresh(interaction)
        return interaction

    def list_by_lead(self, lead_id: int) -> list[Interaction]:
        """依時間由新到舊，這就是 Lead Detail 頁 Timeline 的排列順序。"""
        stmt = (
            select(Interaction)
            .where(Interaction.lead_id == lead_id)
            .order_by(Interaction.created_at.desc(), Interaction.id.desc())
        )
        return list(self.db.execute(stmt).scalars())

    def get(self, interaction_id: int) -> Interaction | None:
        return self.db.get(Interaction, interaction_id)

    def delete(self, interaction: Interaction) -> None:
        self.db.delete(interaction)
        self.db.commit()
