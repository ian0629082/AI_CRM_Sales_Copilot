"""跟進建議的 Criteria-based 評估判準。

跟 metrics.py 一樣不碰網路、不碰資料庫，純粹是「看一則建議，判斷它合不合格」。
獨立出來的理由也一樣：**評估程式本身會寫錯**，
而一份算錯的數字比沒有數字更糟 —— 它會讓人對著錯的方向調 prompt。
所以它有自己的單元測試（tests/test_followup_criteria.py）。

---

## 為什麼不能沿用 Sprint 4 那一套

Sprint 4 算的是「模型抽出來的欄位跟人工標註的答案一不一樣」。
那套機制的前提是**有標準答案**。

跟進建議沒有標準答案。同一位客戶，「先打電話確認他考慮得如何」
跟「先把上次談到的物件資料傳過去」都是合理的建議，
不能因為模型選了其中一個就說它錯。

所以這裡改成問一組**判準**：不問「答案對不對」，問「這則建議有沒有踩到紅線、
有沒有做到該做的事」。每一條判準單獨計算通過率，不加權成一個總分 ——
加權會讓「捏造」被「語氣不錯」補回來，而捏造是不能被補的。

## 三層判準，可信度由高到低

| 層 | 判準 | 誰來判 | 可信度 |
|---|---|---|---|
| 1 | 引用有沒有出處、有沒有用到互動歷史、是不是空話 | 程式 | 確定性，最可信 |
| 2 | 語氣自不自然、動作具不具體 | LLM Judge | 會出錯，要抽樣校準 |
| 3 | 整體可不可用 | 人 | 最貴，只抽樣 |

這個檔案負責第一層。第二層在 scripts/evaluate_followup.py，
第三層是人工的事，腳本只負責把抽樣案例整理出來給人看。

**第一層是主指標**，不是暖身。它涵蓋的正是最不能妥協的那件事：
CRM 裡不能出現客戶從沒說過的資訊。
第二層只能拿來看趨勢，因為判官本身也是同一類模型，它會出錯，
而且它的錯誤跟被評估的模型可能是相關的（同樣的偏好、同樣的盲點）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dataclass_field
from enum import Enum

# 空話清單。
#
# 這些話出現在「下一步動作」等於沒給建議 —— 業務看完還是不知道要幹嘛。
# 由具業務經驗的人列出，不是憑感覺想的：
# 這正是主管在早會上講完之後，業務回到座位仍然不會動的那幾句。
EMPTY_ACTION_PHRASES: tuple[str, ...] = (
    "持續追蹤",
    "保持聯繫",
    "保持聯絡",
    "持續關注",
    "再聯絡",
    "再跟進",
    "定期追蹤",
    "密切注意",
    "持續溝通",
)

# 下一步動作的最短長度。
# 少於這個字數不可能講清楚一個具體動作，多半是「打電話」這種半句話。
MIN_ACTION_LENGTH = 6


class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    # 這一條在這個案例上不適用（例如沒有互動紀錄，就無從要求它引用互動紀錄）。
    # 不適用要跟通過分開，混在一起算會讓通過率虛高。
    NOT_APPLICABLE = "N/A"


@dataclass(frozen=True)
class CriterionResult:
    name: str
    verdict: Verdict
    # 失敗時說清楚是哪裡失敗，報告才有辦法直接拿來做 Error Analysis
    detail: str = ""


def normalize(text: str) -> str:
    """比對前把空白拿掉。與 follow_up_advisor 用同一條規則。"""
    return "".join(text.split())


def check_grounding(evidence: list[str], source_text: str) -> CriterionResult:
    """引用的每一句，都要逐字出現在客戶說過的話裡。

    這是整組判準裡最重要的一條，也是「有沒有捏造」的可驗證版本。

    注意評估時要用**模型原始的輸出**，不是 API 回給前端的那一份 ——
    正式流程會把找不到出處的引用先拿掉再顯示，
    拿處理過的結果來評估，等於量到 0% 捏造然後開心地收工。
    FollowUpOutcome.ungrounded_evidence 留著就是為了這一刻。
    """
    normalized_source = normalize(source_text)
    bad = [q for q in evidence if not normalize(q) or normalize(q) not in normalized_source]

    if bad:
        return CriterionResult(
            "grounding", Verdict.FAIL, f"{len(bad)} 條引用找不到出處：{bad}"
        )
    return CriterionResult("grounding", Verdict.PASS)


def check_uses_history(evidence: list[str], interaction_text: str) -> CriterionResult:
    """有互動紀錄時，建議必須真的用到它。

    這條判準是在守這個功能的立身之本。
    如果建議只從客戶的需求欄位出發，那業務自己看一眼客戶資料也講得出來，
    不值得為它付一次 API 費用 —— 更不值得讓業務多等六秒。

    沒有互動紀錄的案例回 N/A：第一次聯絡本來就沒有歷史可以引用，
    把它算成失敗會讓這個指標變得無法解讀。
    """
    if not interaction_text.strip():
        return CriterionResult("uses_history", Verdict.NOT_APPLICABLE, "這筆沒有互動紀錄")

    normalized = normalize(interaction_text)
    if any(normalize(q) and normalize(q) in normalized for q in evidence):
        return CriterionResult("uses_history", Verdict.PASS)
    return CriterionResult(
        "uses_history", Verdict.FAIL, "有互動紀錄，但沒有任何一條引用來自它"
    )


def check_actionable(next_action: str) -> CriterionResult:
    """下一步動作不能是空話。

    「持續追蹤」這種建議，業務看完還是不知道要幹嘛。
    它不算錯，但它沒有用 —— 而一個沒有用的功能，業務按兩次就不會再按了。
    """
    text = next_action.strip()

    if len(text) < MIN_ACTION_LENGTH:
        return CriterionResult("actionable", Verdict.FAIL, f"太短：「{text}」")

    hit = [p for p in EMPTY_ACTION_PHRASES if p in text]
    # 只有整句幾乎就是那句空話時才判失敗。
    # 「持續追蹤他對三房的想法」講了具體的事，不該因為前四個字被判死。
    if hit and len(text) <= MIN_ACTION_LENGTH + 4:
        return CriterionResult("actionable", Verdict.FAIL, f"是空話：「{text}」")

    return CriterionResult("actionable", Verdict.PASS)


# 只抓「數字 + 房產單位」的組合，例如 2000 萬、30 坪、12 樓、15 年、3 房。
#
# 一開始抓的是所有阿拉伯數字，第一輪評估就誤判了一筆：
# 話術寫「我先花 1 分鐘跟您確認」，那個 1 被當成沒有出處的數字。
# 它說得沒錯——客戶確實沒講過 1——但那是業務自己的話，不是關於客戶的事實。
#
# 收窄到房產單位，抓的才是真正會出事的那種數字：
# 坪數、價格、樓層、屋齡。業務會照著念，念錯了客戶當場就知道他在編。
#
# 中文數字一律不抓：「三天後再約他」的「三」是模型自己算的時間。
# 一個天天誤報的指標會被忽略，然後真的出事時也沒人看。
_NUMBER = re.compile(r"\d[\d,\.]*\s*(?:萬|億|坪|樓|房|廳|衛|年|元|千)")


def check_numbers_grounded(talking_point: str, source_text: str) -> CriterionResult:
    """話術裡的數字必須在輸入裡出現過。

    這是補 evidence 的漏。evidence 只涵蓋模型「自己承認有引用」的部分，
    話術本身仍然可能夾帶客戶沒說過的東西 —— 而最容易出事、
    也最容易被業務照著念出去的，就是數字：坪數、價格、樓層。

    這只是一條啟發式檢查，會有誤判（模型寫「3 天內」而客戶沒講過 3）。
    所以它的失敗不代表一定捏造，是一份**要人去看一眼**的清單。
    """
    normalized_source = normalize(source_text)
    # 抓出來的字串要跟來源用同一條規則正規化才能比。
    # 「預算 2000 萬」抓到的是帶空白的 "2000 萬"，來源那邊空白已經拿掉了，
    # 少了這一步，每一個帶空白的金額都會被誤判成捏造 ——
    # 而金額正是這條判準最該抓對的東西。
    suspicious = [
        n for n in _NUMBER.findall(talking_point) if normalize(n) not in normalized_source
    ]

    if suspicious:
        return CriterionResult(
            "numbers_grounded", Verdict.FAIL, f"輸入裡沒有這些數字：{suspicious}"
        )
    return CriterionResult("numbers_grounded", Verdict.PASS)


@dataclass
class FollowUpCaseResult:
    """一筆案例的評估結果。"""

    case_id: str
    tags: list[str]
    # 模型的原始輸出，包含後來會被拿掉的引用
    suggestion: dict
    source_text: str
    criteria: list[CriterionResult]
    # LLM Judge 的評分，沒跑 judge 時是 None
    judge: dict | None = None

    def verdict_of(self, name: str) -> Verdict | None:
        return next((c.verdict for c in self.criteria if c.name == name), None)

    @property
    def failures(self) -> list[CriterionResult]:
        return [c for c in self.criteria if c.verdict is Verdict.FAIL]

    @property
    def is_clean(self) -> bool:
        """沒有踩到任何一條判準。這是最貼近「這則建議能不能直接用」的指標。"""
        return not self.failures


def evaluate_case(
    *,
    case_id: str,
    tags: list[str],
    suggestion: dict,
    source_text: str,
    interaction_text: str,
) -> FollowUpCaseResult:
    """對一則建議跑完第一層的四條判準。

    suggestion 收 dict 而不是 FollowUpSuggestion，是為了能直接吃
    存下來的 JSON 報告重跑 —— 改了判準之後，不必再花一次錢重打模型。
    """
    evidence = list(suggestion.get("evidence") or [])

    return FollowUpCaseResult(
        case_id=case_id,
        tags=tags,
        suggestion=suggestion,
        source_text=source_text,
        criteria=[
            check_grounding(evidence, source_text),
            check_uses_history(evidence, interaction_text),
            check_actionable(suggestion.get("next_action", "")),
            check_numbers_grounded(suggestion.get("talking_point", ""), source_text),
        ],
    )


# 報告裡判準的排列順序，由重要到次要
CRITERIA_ORDER: tuple[str, ...] = (
    "grounding",
    "uses_history",
    "actionable",
    "numbers_grounded",
)

CRITERIA_LABELS: dict[str, str] = {
    "grounding": "引用有出處（沒有捏造）",
    "uses_history": "有用到互動歷史",
    "actionable": "下一步是具體動作",
    "numbers_grounded": "話術裡的數字有出處",
}


@dataclass
class CriterionStats:
    passed: int = 0
    failed: int = 0
    not_applicable: int = 0

    @property
    def applicable(self) -> int:
        return self.passed + self.failed

    @property
    def pass_rate(self) -> float | None:
        """通過率的分母**不含** N/A。

        把不適用的案例算成通過，會讓「有用到互動歷史」這條在
        一份全是新客戶的資料集上顯示 100%，而實際上它一次都沒被考過。
        """
        return self.passed / self.applicable if self.applicable else None


@dataclass
class FollowUpReport:
    model: str
    prompt_version: str
    cases: list[FollowUpCaseResult] = dataclass_field(default_factory=list)
    failed_cases: list[tuple[str, str]] = dataclass_field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latencies_ms: list[int] = dataclass_field(default_factory=list)

    @property
    def per_criterion(self) -> dict[str, CriterionStats]:
        stats = {name: CriterionStats() for name in CRITERIA_ORDER}
        for case in self.cases:
            for result in case.criteria:
                bucket = stats.setdefault(result.name, CriterionStats())
                if result.verdict is Verdict.PASS:
                    bucket.passed += 1
                elif result.verdict is Verdict.FAIL:
                    bucket.failed += 1
                else:
                    bucket.not_applicable += 1
        return stats

    @property
    def clean_rate(self) -> float | None:
        """四條判準全過的案例比例。

        這是這份報告的頭條數字。逐條通過率會出現
        「每條都 90%，但沒有一則建議是四條全過」的情況 ——
        而業務拿到的是一整則建議，不是四條分開的指標。
        """
        if not self.cases:
            return None
        return sum(1 for c in self.cases if c.is_clean) / len(self.cases)

    @property
    def median_latency_ms(self) -> int | None:
        if not self.latencies_ms:
            return None
        ordered = sorted(self.latencies_ms)
        return ordered[len(ordered) // 2]
