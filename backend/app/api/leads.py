"""Lead 的 REST API。

這一層刻意寫得很薄：驗證輸入 → 呼叫 Service → 回傳。
只要看到 route 裡開始出現 if/else 商業判斷，就代表該搬去 Service 了。
"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.enums import LeadStatus
from app.models.user import User
from app.schemas.lead import (
    LeadCreate,
    LeadDetail,
    LeadListResponse,
    LeadRead,
    LeadUpdate,
)
from app.services.lead_service import LeadService

router = APIRouter(prefix="/leads", tags=["leads"])


def get_lead_service(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LeadService:
    """把登入者綁進 Service。

    授權寫在這個 dependency 裡，而不是每支 route 各寫一次 —— 
    少了重複，也就少了某支 API 忘記加保護的可能。
    """
    return LeadService(db, current_user)


@router.post("", response_model=LeadRead, status_code=status.HTTP_201_CREATED)
def create_lead(
    payload: LeadCreate,
    service: LeadService = Depends(get_lead_service),
):
    return service.create_lead(payload)


@router.get("", response_model=LeadListResponse)
def list_leads(
    status_filter: LeadStatus | None = Query(default=None, alias="status"),
    keyword: str | None = Query(default=None, description="比對姓名或電話"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    service: LeadService = Depends(get_lead_service),
):
    items, total = service.list_leads(
        status=status_filter, keyword=keyword, skip=skip, limit=limit
    )
    return LeadListResponse(items=items, total=total)


@router.get("/{lead_id}", response_model=LeadDetail)
def get_lead(lead_id: int, service: LeadService = Depends(get_lead_service)):
    """回傳單一 Lead，並附上互動紀錄 Timeline。"""
    return service.get_lead_detail(lead_id)


@router.patch("/{lead_id}", response_model=LeadRead)
def update_lead(
    lead_id: int,
    payload: LeadUpdate,
    service: LeadService = Depends(get_lead_service),
):
    return service.update_lead(lead_id, payload)


@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lead(lead_id: int, service: LeadService = Depends(get_lead_service)):
    service.delete_lead(lead_id)
