"""Lead 的商業邏輯層。

API 只負責收發 HTTP，Repository 只負責讀寫資料庫，
中間所有「該不該做、做了要連帶做什麼」的判斷都放在這裡。

Service 在建構時就綁定目前登入者，所有操作自動限定在自己的客戶範圍內。
Sprint 5 加入 Lead Scoring 時，呼叫 ScoringService 的位置也在這一層。
"""

import logging
from datetime import date

from sqlalchemy.orm import Session

from app.core.exceptions import AIServiceError, NotFoundError, ValidationError
from app.models.ai_analysis import AIAnalysis
from app.models.enums import LeadStatus
from app.models.lead import Lead
from app.models.user import User
from app.repositories.ai_analysis_repository import AIAnalysisRepository
from app.repositories.lead_repository import LeadRepository
from app.schemas.lead import LeadCreate, LeadUpdate
from app.services import follow_up
from app.services.ai_service import AIService
from app.services.scoring_service import calculate_score

logger = logging.getLogger(__name__)

REQUIREMENT_PARSING = "REQUIREMENT_PARSING"


class LeadService:
    def __init__(self, db: Session, current_user: User, ai_service: AIService | None = None):
        self.repo = LeadRepository(db)
        self.analysis_repo = AIAnalysisRepository(db)
        self.current_user = current_user
        # AI 是選配的。沒有設定 OPENAI_API_KEY 時 ai_service 是 None，
        # CRM 的其他功能照常運作 —— 這正是「AI 是 Enhancement，不是地基」的具體寫法。
        self.ai_service = ai_service

    def create_lead(self, payload: LeadCreate) -> Lead:
        lead = Lead(**payload.model_dump(), owner_id=self.current_user.id)
        self._apply_score(lead)
        return self.repo.create(lead)

    @staticmethod
    def _apply_score(lead: Lead) -> None:
        """重算並寫回分數。

        分數存在 lead 上（而不是每次查詢時才算），是因為列表頁要用它排序 ——
        排序得在 SQL 裡做，不能把幾百筆撈回來再用 Python 排。

        理由則不存：規則是確定性的，隨時重算得到的結果一定一樣，
        存起來只會多一份可能過期的副本。
        """
        result = calculate_score(lead)
        lead.lead_score = result.score
        lead.lead_level = result.level

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

        # 掛一個非資料庫欄位上去給 schema 讀。
        # 理由不存資料庫，所以在這裡即時算出來。
        lead.score_reasons = calculate_score(lead).reasons
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
        # 改了需求欄位，分數就過期了 —— 在同一個地方一起更新，
        # 不要留給呼叫端記得要重算。
        self._apply_score(lead)
        return self.repo.save(lead)

    def delete_lead(self, lead_id: int) -> None:
        lead = self.get_lead(lead_id)
        self.repo.delete(lead)

    def list_follow_ups(self, today: date | None = None) -> tuple[list, list, int]:
        """算出今天的待跟進清單。

        判斷在 Python 裡做而不是寫成 SQL：規則有「有沒有互動紀錄」這種
        跨表的條件，寫成 SQL 會變得很難讀，而且一個業務手上的客戶數
        是幾百筆的量級，全撈回來判斷完全不是問題。

        真的長到需要在 SQL 裡篩時，next_follow_up_at 已經有索引了。
        """
        today = today or date.today()
        leads = self.repo.list_for_follow_up(self.current_user.id)

        new_uncontacted, due = [], []
        muted_count = 0

        for lead in leads:
            status = follow_up.evaluate(lead, list(lead.interactions), today)
            if status.bucket is follow_up.FollowUpBucket.MUTED:
                muted_count += 1
            elif status.bucket is follow_up.FollowUpBucket.NEW_UNCONTACTED:
                new_uncontacted.append((lead, status))
            elif status.bucket is follow_up.FollowUpBucket.DUE:
                due.append((lead, status))

        # 拖越久的排越前面；同樣久的，分數高的優先
        def priority(item):
            lead, status = item
            return (-status.days_overdue, -(lead.lead_score or 0))

        new_uncontacted.sort(key=priority)
        due.sort(key=priority)
        return new_uncontacted, due, muted_count

    # ------------------------------------------------------------------
    # AI 需求解析（Sprint 3）
    # ------------------------------------------------------------------

    def analyze_lead(self, lead_id: int) -> tuple[Lead, AIAnalysis]:
        """把客戶原話丟給 AI 解析，結果寫回 lead 欄位，並留下一筆分析紀錄。

        流程刻意都放在 Service 層：日後 n8n（Sprint 8）收到表單、
        或 Agent（Sprint 11）要分析客戶時，呼叫的是同一個方法，
        不會出現「網頁上會推進狀態、n8n 進來的就不會」這種不一致。
        """
        lead = self.get_lead(lead_id)

        if self.ai_service is None:
            raise AIServiceError("伺服器尚未設定 AI 功能")

        raw = (lead.raw_requirement or "").strip()
        if not raw:
            # 422 而不是 503：這不是 AI 壞了，是這筆客戶根本沒有原話可以分析。
            # 兩者要分得開，前端才知道該顯示「請先填寫客戶需求」還是「請稍後重試」。
            raise ValidationError("這位客戶還沒有原始需求描述，無法進行 AI 解析")

        outcome = self.ai_service.parse_requirement(raw)
        updated_fields = self._apply_requirement(lead, outcome.requirement)
        self._apply_score(lead)

        analysis = self.analysis_repo.create(
            AIAnalysis(
                lead_id=lead.id,
                analysis_type=REQUIREMENT_PARSING,
                # 存原話的快照而不是指向 lead.raw_requirement：
                # 業務事後編輯原話時，這筆紀錄仍然對得上當時的輸出。
                input_text=raw,
                parsed_result=outcome.requirement.model_dump(mode="json"),
                prompt_version=outcome.prompt_version,
                model=outcome.model,
                prompt_tokens=outcome.prompt_tokens,
                completion_tokens=outcome.completion_tokens,
                latency_ms=outcome.latency_ms,
            )
        )

        lead = self.repo.save(lead)
        logger.info(
            "Lead %s 完成 AI 解析，更新欄位：%s",
            lead_id,
            ", ".join(updated_fields) or "（無）",
        )
        return lead, analysis

    @staticmethod
    def _apply_requirement(lead: Lead, requirement) -> list[str]:
        """把解析結果寫回 lead，回傳實際被改動的欄位名稱。

        **只填、不清空**：AI 回 None 代表「客戶沒提到」，不代表「這個值不對」。
        若讓 None 覆蓋掉業務手動輸入的內容，業務只要按一次「AI 解析」，
        自己剛填好的資料就消失了 —— 那是會讓人再也不敢按那顆按鈕的行為。

        要清空欄位，業務用一般的編輯功能處理，那是明確的意圖表達。
        """
        updated: list[str] = []
        for field, value in requirement.model_dump().items():
            if value is None:
                continue
            # budget_is_approximate 是 bool（不會是 None），沒有預算時的 false
            # 只是預設值，不該被當成「AI 判斷這筆預算很精確」而蓋掉舊資料。
            if field == "budget_is_approximate" and requirement.budget_max is None:
                continue
            if getattr(lead, field) != value:
                setattr(lead, field, value)
                updated.append(field)
        return updated
