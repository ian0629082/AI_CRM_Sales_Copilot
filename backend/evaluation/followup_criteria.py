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


# 模型有時會自己在引用外面加一對引號來表示「這是引述」。
# 那對符號是它的排版習慣，不是它引用的內容。
_WRAPPING_QUOTES = "「」『』\"'“”‘’"


def normalize(text: str) -> str:
    """比對前把空白與首尾引號拿掉。與 follow_up_advisor 用同一條規則。

    ### 首尾引號這條是**在看過 holdout 的失敗之後才加的**

    這件事必須寫在這裡，因為「數字不好看就放寬判準」正是這個動作的形狀。

    當時 holdout 有一筆判成捏造，內容是：

        模型引用：「我要找城市之星這個社區，因為我家人也住這個社區⋯⋯」
        來源原文： 我要找城市之星這個社區，因為我家人也住這個社區⋯⋯

    一字不差，只差首尾那對「」。

    判斷「這是修正誤判還是放寬標準」的標準只有一條：
    **改完之後，這條判準會不會放過真正的捏造？**
    不會 —— 拿掉的只有最外層的引號，內容仍然必須逐字相符。
    改寫一個字、接兩句話、引用系統整理過的欄位，全部照樣判失敗。

    只脫最外層，不脫中間的。句子中間出現的引號是內容的一部分：
    客戶說「他說『再看看』」，那個『再看看』不能被拿掉。
    """
    stripped = "".join(text.split())
    return stripped.strip(_WRAPPING_QUOTES)


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


# 客戶「明確約定下次回電時間」的說法。這幾個詞本身就指向聯絡，不必看上下文。
_APPOINTMENT = re.compile(
    r".{0,12}(?:再打給|再聯絡|再回你|再回我|再撥|再找我|再約|再通知|打給我|聯絡我)"
)

# 「有空」「方便」要看上下文才知道在講什麼。
#
# 這一條是業務實務判斷：同樣一句「我只有週六下午有空」，
# 可能是「你週六下午再打給我」，也可能是「我週六下午才能去看房子」。
# 兩者對業務的意義完全相反——前者要照做，後者不必等。
#
# 所以往前後各看一段字，判斷這句話是在講聯絡還是看屋。
# 判斷不出來時回「不確定」，然後**不判失敗**：
# 這條判準寧可漏抓，也不要誤殺一則其實正常的建議——
# 一個會誤報的指標，業務看兩次就不看了。
_AVAILABILITY = re.compile(r"有空|方便")
_CONTEXT_WINDOW = 15

_VIEWING_WORDS = ("看屋", "帶看", "看房", "賞屋", "約看", "去看", "現場", "見面", "面談")
_CONTACT_WORDS = ("電話", "打給", "打來", "聯絡", "回電", "通話", "LINE", "訊息", "傳給")


class AppointmentKind(str, Enum):
    """客戶約的是什麼。"""

    CONTACT = "CONTACT"  # 約好下次聯絡的時間，建議時機必須照做
    VIEWING = "VIEWING"  # 約好看屋的時間，不必等到那時候才打電話
    NONE = "NONE"  # 沒有約，或看不出來在講什麼


def classify_appointment(source_text: str) -> tuple[AppointmentKind, str]:
    """客戶有沒有約時間、約的是聯絡還是看屋。

    回傳 (種類, 那段原話)。抽成獨立函式是因為它同時被兩個地方用到：
    這裡的判準，以及日後要做「帶看前一天提醒業務確認」時的判斷。
    """
    # 明確的回電約定優先。「叫我下週三再打給你」不管前後文都是聯絡。
    explicit = [m.group(0) for m in _APPOINTMENT.finditer(source_text)]
    if explicit:
        return AppointmentKind.CONTACT, " ".join(explicit)

    for match in _AVAILABILITY.finditer(source_text):
        start = max(0, match.start() - _CONTEXT_WINDOW)
        window = source_text[start : match.end() + _CONTEXT_WINDOW]

        has_viewing = any(w in window for w in _VIEWING_WORDS)
        has_contact = any(w in window for w in _CONTACT_WORDS)

        # 兩種詞同時出現時當成看屋。
        # 「我打電話跟你約，我只有週六下午有空」講的還是看屋的時間，
        # 那個「打電話」只是他描述怎麼約，不是他要求你何時打。
        if has_viewing:
            return AppointmentKind.VIEWING, window
        if has_contact:
            return AppointmentKind.CONTACT, window

    return AppointmentKind.NONE, ""

# 日期層級的時間詞。這一級才算「約好了哪一天」。
_DAY = re.compile(
    r"下下週[一二三四五六日天]|下週[一二三四五六日天]|這週[一二三四五六日天]"
    r"|禮拜[一二三四五六日天]|週[一二三四五六日天]"
    r"|大後天|後天|明天|下週|下個月|\d{1,2}號"
)

# 只有時段沒有日期時才看這一級。
# 「下午」單獨出現不足以構成約定——「今天下午」也含「下午」，
# 用它來比對的話，客戶約下週三下午、業務今天下午打，會被判成通過。
_TIME_OF_DAY = re.compile(r"上午|下午|早上|中午|傍晚|晚上|下班前")


def check_timing_matches_appointment(
    suggested_timing: str, source_text: str
) -> CriterionResult:
    """客戶自己約了時間，建議時機就要照他講的。

    這條判準是**業務實務判斷**，不是我想出來的：
    客戶說「叫我下週三下午再打給你」，業務今天下午就打過去，
    等於沒把他的話當一回事。客戶掛電話前講的那句話，
    是他給的最明確的指示，比任何規則都準。

    這也是前四條判準結構性看不到的一類錯誤。
    第一輪 v3 的評估裡，fu-006 引用得完全正確（那句話它逐字摘出來了）、
    grounding 判 PASS，然後建議業務今天就打。
    前四條檢查的是「有沒有亂講」，這一條檢查的是「講得對不對」。

    日期跟時段分兩級比對：客戶講到哪一天，就必須對到哪一天。
    只比對「下午」的話，「客戶約下週三下午、業務今天下午打」會被判成通過——
    而那正是這條判準唯一要抓的東西。
    """
    kind, promised = classify_appointment(source_text)

    if kind is AppointmentKind.NONE:
        return CriterionResult(
            "timing_matches", Verdict.NOT_APPLICABLE, "客戶沒有指定下次聯絡時間"
        )

    if kind is AppointmentKind.VIEWING:
        # 客戶約的是看屋時間，不是回電時間。
        # 業務要打電話確認一件事，不必等到他有空看房——
        # 事實上正好相反：帶看前一天就該先聯絡確認（見 follow_up.py）。
        return CriterionResult(
            "timing_matches", Verdict.NOT_APPLICABLE, "客戶講的是看屋時間，不是回電時間"
        )
    days = _DAY.findall(promised)
    if days:
        if any(day in suggested_timing for day in days):
            return CriterionResult("timing_matches", Verdict.PASS)
        return CriterionResult(
            "timing_matches",
            Verdict.FAIL,
            f"客戶約的是「{days[0]}」，建議時機卻是「{suggested_timing}」",
        )

    slots = _TIME_OF_DAY.findall(promised)
    if slots:
        if any(slot in suggested_timing for slot in slots):
            return CriterionResult("timing_matches", Verdict.PASS)
        return CriterionResult(
            "timing_matches",
            Verdict.FAIL,
            f"客戶約的是「{slots[0]}」，建議時機卻是「{suggested_timing}」",
        )

    # 有約定的說法但抓不出時間詞（例如「有物件再通知我」）。
    # 那不是約時間，是把決定權交給業務，不該要求時機對得上。
    return CriterionResult(
        "timing_matches", Verdict.NOT_APPLICABLE, "客戶有提到再聯絡，但沒講明時間"
    )


# 「確認帶看」這件事講得出來的說法。
# 動詞跟受詞分開比對，是因為「跟她確認明天看屋的時間」與
# 「確認一下明天帶看還算數嗎」都算數，但字面上沒有共同的片語。
_CONFIRM_VERBS = ("確認", "確定", "再確認", "跟他確認", "跟她確認")
_VIEWING_NOUNS = ("帶看", "看屋", "看房", "賞屋", "約看", "明天")


def check_viewing_confirmed(
    next_action: str, talking_point: str, viewing_is_tomorrow: bool
) -> CriterionResult:
    """明天要帶看的客戶，建議必須是去確認那個約。

    這條判準守的是一條業務實務規則：帶看前一天一定要先聯絡客戶確認。
    客戶臨時有事卻沒講，業務白跑一趟，而那個下午本來可以帶另一組客戶。

    為什麼要有這條判準：規則已經寫進 prompt 了，但**沒有人在驗它有沒有照做**。
    只寫 prompt 不寫判準，等於把規則交給模型的心情；
    只寫判準不寫 prompt，則是抓錯不修錯。兩邊都要有。

    沒有帶看約的案例回 N/A —— 這條判準只在那一天有意義。
    """
    if not viewing_is_tomorrow:
        return CriterionResult("viewing_confirmed", Verdict.NOT_APPLICABLE, "明天沒有帶看")

    text = f"{next_action}　{talking_point}"
    if any(v in text for v in _CONFIRM_VERBS) and any(n in text for n in _VIEWING_NOUNS):
        return CriterionResult("viewing_confirmed", Verdict.PASS)

    return CriterionResult(
        "viewing_confirmed",
        Verdict.FAIL,
        f"明天就要帶看，建議卻沒有叫業務去確認：「{next_action}」",
    )


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
    viewing_is_tomorrow: bool = False,
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
            check_timing_matches_appointment(
                suggestion.get("suggested_timing", ""), source_text
            ),
            check_viewing_confirmed(
                suggestion.get("next_action", ""),
                suggestion.get("talking_point", ""),
                viewing_is_tomorrow,
            ),
        ],
    )


# 報告裡判準的排列順序，由重要到次要
CRITERIA_ORDER: tuple[str, ...] = (
    "grounding",
    "viewing_confirmed",
    "timing_matches",
    "uses_history",
    "actionable",
    "numbers_grounded",
)

CRITERIA_LABELS: dict[str, str] = {
    "grounding": "引用有出處（沒有捏造）",
    "viewing_confirmed": "明天帶看要叫業務去確認",
    "timing_matches": "時機對得上客戶約的時間",
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
