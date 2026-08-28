"""Lead 的 REST API。

這一層刻意寫得很薄：驗證輸入 → 呼叫 Service → 回傳。
只要看到 route 裡開始出現 if/else 商業判斷，就代表該搬去 Service 了。
"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_ai_service, get_current_user, get_follow_up_advisor
from app.db.database import get_db
from app.models.enums import LeadStatus
from app.models.user import User
from app.schemas.lead import (
    FollowUpItem,
    FollowUpResponse,
    LeadAnalyzeResponse,
    LeadCreate,
    LeadDetail,
    LeadFollowUpResponse,
    LeadListResponse,
    LeadRead,
    LeadUpdate,
)
from app.services.ai_service import AIService
from app.services.follow_up_advisor import FollowUpAdvisor
from app.services.lead_service import LeadService

router = APIRouter(prefix="/leads", tags=["leads"])


def get_lead_service(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    ai_service: AIService | None = Depends(get_ai_service),
    advisor: FollowUpAdvisor | None = Depends(get_follow_up_advisor),
) -> LeadService:
    """把登入者綁進 Service。

    授權寫在這個 dependency 裡，而不是每支 route 各寫一次 ——
    少了重複，也就少了某支 API 忘記加保護的可能。
    """
    return LeadService(db, current_user, ai_service, advisor)


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


@router.get("/follow-ups", response_model=FollowUpResponse)
def list_follow_ups(service: LeadService = Depends(get_lead_service)):
    """今天該聯絡誰。

    路由必須註冊在 /{lead_id} 之前，否則 "follow-ups" 會被當成 lead_id
    去比對，然後回一個看起來莫名其妙的 422。
    """
    viewing_confirm, new_uncontacted, due, muted_count = service.list_follow_ups()

    def to_items(rows):
        return [
            FollowUpItem(
                lead=lead,
                bucket=status.bucket.value,
                days_overdue=status.days_overdue,
                reason=status.reason,
            )
            for lead, status in rows
        ]

    return FollowUpResponse(
        viewing_confirm=to_items(viewing_confirm),
        new_uncontacted=to_items(new_uncontacted),
        due=to_items(due),
        muted_count=muted_count,
    )


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


@router.post("/{lead_id}/analyze", response_model=LeadAnalyzeResponse)
def analyze_lead(lead_id: int, service: LeadService = Depends(get_lead_service)):
    """把客戶原話交給 AI 解析，結果直接寫回這位客戶的需求欄位。

    同步等待（約 2～5 秒），前端顯示 loading。
    做成同步是因為 MVP 階段一次只分析一筆，排背景工作要多一個 queue 與輪詢機制，
    複雜度換不到對應的好處；真的要批次分析時再改。

    **原話沒變的話不會重新呼叫模型**，直接沿用上一次的結果並把 `reused`
    設成 true。同一段話重算一次結果本來就會一樣，那是純粹的浪費；
    業務改了原話（客戶需求變了）再按，才是真的重新解析。

    可能的失敗：
    - 404 這位客戶不存在（或不是你的）
    - 422 這位客戶還沒填原始需求
    - 503 AI 暫時不可用 —— 客戶資料本身不受影響，前端顯示重試按鈕
    """
    lead, analysis, reused = service.analyze_lead(lead_id)
    return LeadAnalyzeResponse(lead=lead, analysis=analysis, reused=reused)


@router.post("/{lead_id}/follow-up-suggestion", response_model=LeadFollowUpResponse)
def suggest_follow_up(lead_id: int, service: LeadService = Depends(get_lead_service)):
    """產生一則 AI 跟進建議：下一步動作、建議話術、建議時機。

    由業務按按鈕觸發，同步等待。不做成「打開待跟進頁面就自動全部產生」——
    一次列表可能有二十位客戶，那就是二十次 API 呼叫，
    而業務今天其實只會打其中三通。

    **這支 API 不會改動客戶的任何欄位**，包括下次提醒日。
    建議是參考，不是系統替業務做的決定。

    可能的失敗：
    - 404 這位客戶不存在（或不是你的）
    - 422 這位客戶既沒有原始需求也沒有互動紀錄，沒有東西可以據以建議
    - 503 AI 暫時不可用
    """
    _, analysis = service.suggest_follow_up(lead_id)
    return LeadFollowUpResponse(suggestion=analysis)


@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lead(lead_id: int, service: LeadService = Depends(get_lead_service)):
    service.delete_lead(lead_id)
