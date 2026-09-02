"""Lead 的商業邏輯層。

API 只負責收發 HTTP，Repository 只負責讀寫資料庫，
中間所有「該不該做、做了要連帶做什麼」的判斷都放在這裡。

Service 在建構時就綁定目前登入者，所有操作自動限定在自己的客戶範圍內。
Sprint 5 加入 Lead Scoring 時，呼叫 ScoringService 的位置也在這一層。
"""

import logging
from datetime import date

from sqlalchemy.orm import Session

from app.core.clock import local_day_start_utc
from app.core.config import settings
from app.core.exceptions import (
    AIServiceError,
    NotFoundError,
    RateLimitError,
    ValidationError,
)
from app.models.ai_analysis import FOLLOW_UP, REQUIREMENT_PARSING, AIAnalysis
from app.models.enums import LeadStatus
from app.models.lead import Lead
from app.models.user import User
from app.repositories.ai_analysis_repository import AIAnalysisRepository
from app.repositories.lead_repository import LeadRepository
from app.schemas.lead import LeadCreate, LeadUpdate
from app.services import follow_up, follow_up_advisor
from app.services.ai_service import AIService
from app.services.follow_up_advisor import FollowUpAdvisor
from app.services.scoring_service import calculate_score

logger = logging.getLogger(__name__)


class LeadService:
    def __init__(
        self,
        db: Session,
        current_user: User,
        ai_service: AIService | None = None,
        advisor: FollowUpAdvisor | None = None,
    ):
        self.repo = LeadRepository(db)
        self.analysis_repo = AIAnalysisRepository(db)
        self.current_user = current_user
        # AI 是選配的。沒有設定 OPENAI_API_KEY 時這兩個都是 None，
        # CRM 的其他功能照常運作 —— 這正是「AI 是 Enhancement，不是地基」的具體寫法。
        self.ai_service = ai_service
        self.advisor = advisor

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

        # 分數與理由必須來自**同一次計算**。
        #
        # 這裡曾經只算理由、分數沿用資料庫存的值，結果畫面上出現
        # 「分數 0，但理由列了 +20 +15 +15 +10」——因為舊資料的
        # lead_score 是 NULL（建立時還沒有計分功能），理由卻是即時算的。
        #
        # 存起來的東西一定會過期，所以讀取時一律重算，
        # 順手把過期的值寫回去（規則是確定性的，寫回去不會有副作用）。
        result = calculate_score(lead)
        lead.score_reasons = result.reasons

        if lead.lead_score != result.score or lead.lead_level != result.level:
            lead.lead_score = result.score
            lead.lead_level = result.level
            self.repo.save(lead)

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

    def list_follow_ups(self, today: date | None = None) -> tuple[list, list, list, int]:
        """算出今天的待跟進清單。

        判斷在 Python 裡做而不是寫成 SQL：規則有「有沒有互動紀錄」這種
        跨表的條件，寫成 SQL 會變得很難讀，而且一個業務手上的客戶數
        是幾百筆的量級，全撈回來判斷完全不是問題。

        真的長到需要在 SQL 裡篩時，next_follow_up_at 已經有索引了。
        """
        today = today or date.today()
        leads = self.repo.list_for_follow_up(self.current_user.id)

        viewing_confirm, new_uncontacted, due = [], [], []
        muted_count = 0

        for lead in leads:
            status = follow_up.evaluate(lead, list(lead.interactions), today)
            if status.bucket is follow_up.FollowUpBucket.MUTED:
                muted_count += 1
            elif status.bucket is follow_up.FollowUpBucket.VIEWING_CONFIRM:
                viewing_confirm.append((lead, status))
            elif status.bucket is follow_up.FollowUpBucket.NEW_UNCONTACTED:
                new_uncontacted.append((lead, status))
            elif status.bucket is follow_up.FollowUpBucket.DUE:
                due.append((lead, status))

        # 拖越久的排越前面；同樣久的，分數高的優先
        def priority(item):
            lead, status = item
            return (-status.days_overdue, -(lead.lead_score or 0))

        # 帶看確認那一堆全部都是「明天」，沒有逾期天數可以排，
        # 所以照帶看時間由早到晚排 —— 業務明天的行程本來就是照時間走的。
        viewing_confirm.sort(key=lambda item: item[0].viewing_scheduled_at)
        new_uncontacted.sort(key=priority)
        due.sort(key=priority)
        return viewing_confirm, new_uncontacted, due, muted_count

    # ------------------------------------------------------------------
    # AI 需求解析（Sprint 3）
    # ------------------------------------------------------------------

    def analyze_lead(self, lead_id: int) -> tuple[Lead, AIAnalysis, bool]:
        """把客戶原話丟給 AI 解析，結果寫回 lead 欄位，並留下一筆分析紀錄。

        回傳的第三個值代表「這次有沒有真的呼叫模型」（見下面的原話快照比對）。

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

        cached = self._reusable_analysis(lead_id, raw)
        if cached is not None:
            logger.info("Lead %s 原話未變更，沿用上一次的解析結果", lead_id)
            return lead, cached, True

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
        return lead, analysis, False

    def _reusable_analysis(self, lead_id: int, raw: str) -> AIAnalysis | None:
        """同一段原話已經解析過的話，直接沿用，不要再花一次錢。

        比對的是**原話的內容**，不是「按過幾次」。所以：

        - 原話沒變重複按 → 回上次的結果（結果本來就會一樣，重算是純浪費）
        - 客戶改了需求、業務改了原話 → 真的重新解析（輸入不一樣了，該重跑）

        `input_text` 存的是當時那段原話的快照，這個欄位本來就是為了
        「事後編輯原話時，紀錄仍然對得上當時的輸出」而存的，正好拿來當比對基準。

        **命中快取時不重新套用欄位到 lead。** 那些欄位早就被那次解析填過了，
        現在的值是「當時的解析 + 業務後續的手動修正」——
        再套一次會把業務改對的東西蓋回 AI 原本的錯誤，
        而他按這顆按鈕並沒有要求系統做這件事。

        比對用完全相等而不是忽略空白：業務多打一個標點就重跑，
        代價只是多花一次錢；反過來把「其實改過了」誤判成沒變，
        代價是他改了原話卻發現欄位不動，然後不知道為什麼。
        """
        previous = self.analysis_repo.get_latest(lead_id, REQUIREMENT_PARSING)
        if previous is None or (previous.input_text or "").strip() != raw:
            return None
        return previous

    # ------------------------------------------------------------------
    # AI 跟進建議（Sprint 5）
    # ------------------------------------------------------------------

    def suggest_follow_up(
        self, lead_id: int, today: date | None = None
    ) -> tuple[Lead, AIAnalysis]:
        """產生一則跟進建議，留下紀錄，但**不改動 lead 的任何欄位**。

        跟 analyze_lead 最大的差別就在這裡：需求解析會把結果寫回客戶資料，
        建議不會 —— 它是給業務看的參考，不是關於這位客戶的新事實。
        「下一次什麼時候聯絡」仍然由業務自己決定（見 follow_up.py），
        AI 給的時機只是一句話，不會偷偷改掉 next_follow_up_at。

        分數、逾期天數都是 Rule Engine 先算好才餵給模型的，
        不讓它自己判斷這位客戶熱不熱、拖了幾天。
        """
        if self.advisor is None:
            raise AIServiceError("伺服器尚未設定 AI 功能")

        # 用 get_with_interactions 而不是 get_lead：建議的重點就是互動歷史，
        # 少了它，AI 只能講一些從客戶需求欄位推得出來的空話。
        lead = self.repo.get_with_interactions(lead_id, self.current_user.id)
        if lead is None:
            raise NotFoundError(f"Lead {lead_id} 不存在")

        interactions = list(lead.interactions)
        if not (lead.raw_requirement or "").strip() and not interactions:
            # 422 而不是 503：這不是 AI 壞了，是這位客戶身上什麼資料都沒有。
            # 硬要產生的話，模型只能靠猜 —— 而猜出來的東西正是我們最不想要的。
            raise ValidationError(
                "這位客戶還沒有原始需求，也沒有任何互動紀錄，無法產生跟進建議"
            )

        # 額度檢查排在權限與資料檢查之後、呼叫模型之前。
        #
        # 順序是刻意的：查不到的客戶要回 404（回 429 等於承認那筆資料存在），
        # 而額度必須在花錢之前擋下來 —— 檢查放在模型呼叫之後就毫無意義了。
        used = self.analysis_repo.count_since(
            self.current_user.id, FOLLOW_UP, local_day_start_utc()
        )
        limit = settings.FOLLOW_UP_DAILY_LIMIT
        if used >= limit:
            logger.info(
                "使用者 %s today 已用 %s 次跟進建議，達到上限 %s",
                self.current_user.id,
                used,
                limit,
            )
            raise RateLimitError(
                f"今天的 AI 跟進建議已經用完 {limit} 次，明天零點會重新計算。"
                "已經產生過的建議仍然看得到。"
            )

        today = today or date.today()
        score = calculate_score(lead)
        status = follow_up.evaluate(lead, interactions, today)

        outcome = self.advisor.suggest(lead, interactions, score, status, today)

        analysis = self.analysis_repo.create(
            AIAnalysis(
                lead_id=lead.id,
                analysis_type=FOLLOW_UP,
                # 存的是整包 context 而不只是客戶原話。
                # 建議的品質取決於當時餵了什麼進去，只存原話的話，
                # 日後看到一則奇怪的建議，會查不出當時模型到底知道多少。
                input_text=outcome.context,
                parsed_result=outcome.suggestion.model_dump(mode="json"),
                suggestion=follow_up_advisor.compose_text(outcome.suggestion),
                score_snapshot=score.score,
                level_snapshot=score.level.value,
                prompt_version=outcome.prompt_version,
                model=outcome.model,
                prompt_tokens=outcome.prompt_tokens,
                completion_tokens=outcome.completion_tokens,
                latency_ms=outcome.latency_ms,
            )
        )

        logger.info("Lead %s 產生跟進建議，分數快照 %s", lead_id, score.score)
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
