"""Lead 的商業邏輯層。

API 只負責收發 HTTP，Repository 只負責讀寫資料庫，
中間所有「該不該做、做了要連帶做什麼」的判斷都放在這裡。

Service 在建構時就綁定目前登入者，所有操作自動限定在自己的客戶範圍內。
Sprint 5 加入 Lead Scoring 時，呼叫 ScoringService 的位置也在這一層。
"""

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.enums import LeadStatus
from app.models.lead import Lead
from app.models.user import User
from app.repositories.lead_repository import LeadRepository
from app.schemas.lead import LeadCreate, LeadUpdate


class LeadService:
    def __init__(self, db: Session, current_user: User):
        self.repo = LeadRepository(db)
        self.current_user = current_user

    def create_lead(self, payload: LeadCreate) -> Lead:
        lead = Lead(**payload.model_dump(), owner_id=self.current_user.id)
        return self.repo.create(lead)

    def get_lead(self, lead_id: int) -> Lead:
        lead = self.repo.get_for_owner(lead_id, self.current_user.id)
        if lead is None:
            # 別人的客戶一律回 404 而非 403。
            # 回 403 等於告訴對方「這個 id 存在，只是不給你看」，
            # 攻擊者就能靠列舉 id 推測系統裡有多少客戶。
            raise NotFoundError(f"Lead {lead_id} 不存在")
        return lead

    def get_lead_detail(self, lead_id: int) -> Lead:
        """Lead Detail 頁用：一併載入互動紀錄。

        用 selectinload 一次撈完，避免前端一頁客戶詳情就打出 N+1 次查詢
        —— 資料庫在新加坡，每多一次來回就是幾十毫秒。
        """
        lead = self.repo.get_with_interactions(lead_id, self.current_user.id)
        if lead is None:
            raise NotFoundError(f"Lead {lead_id} 不存在")
        return lead

    def list_leads(
        self,
        *,
        status: LeadStatus | None = None,
        keyword: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[Lead], int]:
        return self.repo.list(
            owner_id=self.current_user.id,
            status=status,
            keyword=keyword,
            skip=skip,
            limit=limit,
        )

    def update_lead(self, lead_id: int, payload: LeadUpdate) -> Lead:
        lead = self.get_lead(lead_id)
        # exclude_unset：只更新前端真的有送來的欄位，
        # 否則 PATCH 會把沒帶到的欄位一律洗成 None。
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(lead, field, value)
        return self.repo.save(lead)

    def delete_lead(self, lead_id: int) -> None:
        lead = self.get_lead(lead_id)
        self.repo.delete(lead)
