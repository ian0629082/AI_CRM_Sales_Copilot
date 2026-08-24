"""Interaction 的 REST API。

路由設計成巢狀（/leads/{lead_id}/interactions），
因為互動紀錄不會單獨存在，它永遠屬於某一位客戶。
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.interaction import InteractionCreate, InteractionRead
from app.services.interaction_service import InteractionService

router = APIRouter(prefix="/leads/{lead_id}/interactions", tags=["interactions"])


def get_interaction_service(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InteractionService:
    return InteractionService(db, current_user)


@router.post("", response_model=InteractionRead, status_code=status.HTTP_201_CREATED)
def create_interaction(
    lead_id: int,
    payload: InteractionCreate,
    service: InteractionService = Depends(get_interaction_service),
):
    return service.create_interaction(lead_id, payload)


@router.get("", response_model=list[InteractionRead])
def list_interactions(
    lead_id: int,
    service: InteractionService = Depends(get_interaction_service),
):
    return service.list_interactions(lead_id)


@router.delete("/{interaction_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_interaction(
    lead_id: int,
    interaction_id: int,
    service: InteractionService = Depends(get_interaction_service),
):
    service.delete_interaction(lead_id, interaction_id)
