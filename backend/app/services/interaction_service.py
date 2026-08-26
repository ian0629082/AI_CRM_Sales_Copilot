"""Interaction 的商業邏輯層。

這一層存在的價值，在 create_interaction 裡看得最清楚：
新增一筆互動不只是「插一列資料」，還要連帶推進 Lead 的狀態。
如果把這段寫在 API route 裡，日後 n8n 或 Agent 也要新增互動時，
就得把同樣的邏輯再抄一次。
"""

import logging
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.enums import LeadStatus
from app.models.interaction import Interaction
from app.models.lead import Lead
from app.models.user import User
from app.repositories.interaction_repository import InteractionRepository
from app.repositories.lead_repository import LeadRepository
from app.services.follow_up import default_follow_up_days
from app.schemas.interaction import InteractionCreate

logger = logging.getLogger(__name__)


class InteractionService:
    def __init__(self, db: Session, current_user: User):
        self.repo = InteractionRepository(db)
        self.lead_repo = LeadRepository(db)
        self.current_user = current_user

    def _get_own_lead_or_404(self, lead_id: int) -> Lead:
        """確認這位客戶存在，而且屬於目前登入者。

        互動紀錄的權限完全跟著 Lead 走：能看到客戶，才能看到他的互動紀錄。
        """
        lead = self.lead_repo.get_for_owner(lead_id, self.current_user.id)
        if lead is None:
            raise NotFoundError(f"Lead {lead_id} 不存在")
        return lead

    def create_interaction(
        self, lead_id: int, payload: InteractionCreate
    ) -> Interaction:
        lead = self._get_own_lead_or_404(lead_id)

        interaction = self.repo.create(
            Interaction(
                lead_id=lead_id,
                # 這兩個是「要怎麼安排提醒」的指令，不是互動紀錄的內容，
                # 所以不進 Interaction 這張表
                **payload.model_dump(
                    exclude={"next_follow_up_days", "mute_follow_up"}
                ),
            )
        )

        # 只要業務接觸過客戶，這筆 Lead 就不該再停留在 NEW。
        # 只推進 NEW -> CONTACTED，不碰後面的狀態：
        # 已經談到 NEGOTIATING 的客戶，不能因為補記一通電話就被退回 CONTACTED。
        if lead.status == LeadStatus.NEW:
            lead.status = LeadStatus.CONTACTED
            logger.info("Lead %s 因新增互動，狀態由 NEW 推進為 CONTACTED", lead_id)

        self._schedule_follow_up(lead, payload)
        self.lead_repo.save(lead)

        return interaction

    @staticmethod
    def _schedule_follow_up(lead: Lead, payload: InteractionCreate) -> None:
        """設定下次提醒日。

        業務有填就用他填的，沒填就用該互動類型的預設值。
        規則在這裡只是「建議」，不是「決定」—— 業務永遠可以覆蓋。
        """
        if payload.mute_follow_up:
            lead.follow_up_muted = True
            lead.next_follow_up_at = None
            return

        days = payload.next_follow_up_days
        if days is None:
            days = default_follow_up_days(payload.type)

        lead.next_follow_up_at = date.today() + timedelta(days=days)
        # 重新聯絡就等於解除靜音：業務又開始跟這個客戶了
        lead.follow_up_muted = False

    def list_interactions(self, lead_id: int) -> list[Interaction]:
        self._get_own_lead_or_404(lead_id)
        return self.repo.list_by_lead(lead_id)

    def delete_interaction(self, lead_id: int, interaction_id: int) -> None:
        self._get_own_lead_or_404(lead_id)

        interaction = self.repo.get(interaction_id)
        # 檢查 lead_id 是否相符，避免透過 A 客戶的網址刪掉 B 客戶的紀錄
        if interaction is None or interaction.lead_id != lead_id:
            raise NotFoundError(f"Lead {lead_id} 底下沒有 Interaction {interaction_id}")

        self.repo.delete(interaction)
