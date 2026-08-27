"""AI 跟進建議：這位客戶，下一步該怎麼跟。

分層跟 Sprint 3 的需求解析完全一樣，只是換了一個 AIService：

    LeadService          決定「要不要產生、產生完怎麼存」
         ↓
    FollowUpAdvisor      決定「餵什麼 context、用什麼 prompt、怎麼驗證結果」  ← 這個檔案
         ↓
    LLMProvider          只負責「把字串送給模型拿回字串」

沿用同一個 provider Protocol，所以測試一樣不必花錢、不必連網。

---

## 這個功能跟前面的 AI 有什麼根本不同

| | Sprint 3 需求解析 | 這裡的跟進建議 |
|---|---|---|
| 輸出 | 結構化欄位 | 自由文字 |
| 有標準答案嗎 | 有（人工標註） | **沒有** |
| 怎麼評估 | 逐欄位算準確率 | Criteria-based |

「客戶說 2000 萬」的正確答案只有一個，但「該怎麼跟這位客戶」有十種合理的答案。
所以 Sprint 4 那套逐欄位比對的評估機制**不能直接套用**。

那要怎麼確保它沒有亂講？靠 `evidence` 這一欄：
要求模型把話術裡引用到的客戶資訊逐字摘出來，摘出來的句子必須
逐字出現在輸入裡。這把「有沒有捏造」從一個要靠人讀的主觀問題，
變成一個字串比對就能回答的問題（見 `verify_evidence`）。

## Rule Engine 與 LLM 的分工

分數、等級、逾期天數全都是 `scoring_service` 與 `follow_up` 算好才餵進來的，
**不讓模型自己判斷這位客戶熱不熱、拖了幾天**。

理由跟 Sprint 5 不用 LLM 算分是同一條：那些是確定性的規則，
交給模型只會換來一個不穩定又講不清楚的答案。
模型負責的是它真正擅長的那一段 —— 把這些事實寫成一句業務可以直接講出口的話。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import date

from pydantic import ValidationError as PydanticValidationError

from app.core.exceptions import AIServiceError
from app.models.interaction import Interaction
from app.models.lead import Lead
from app.schemas.ai import FollowUpSuggestion
from app.services import follow_up
from app.services.llm_provider import LLMError, LLMProvider
from app.services.scoring_service import ScoreResult

logger = logging.getLogger(__name__)

FOLLOW_UP_PROMPT_V1 = "follow_up_v1"


def _revise(text: str, old: str, new: str) -> str:
    """從上一版 prompt 改出下一版，改不到就當場爆掉。

    新版是用 `.replace()` 從舊版疊出來的（這樣 diff 才看得出「這一版到底改了什麼」），
    但 `.replace()` 有一個很危險的性質：**錨點對不上時它不報錯，只是原封不動回傳。**

    這件事真的發生過：v4 的錨點少算了一個換行，替換靜默失敗，
    結果 v4 的內容跟 v3 一模一樣，而版號、日誌、資料庫紀錄全都顯示是 v4。
    那種錯誤最糟的地方在於評估還是跑得完、報告還是產得出來，
    只是你以為在比較兩個版本，其實在比較同一個版本兩次。

    所以這裡改不到就丟 ValueError —— 模組載入時就會炸，不會拖到跑評估才發現。
    """
    if old not in text:
        raise ValueError(f"prompt 錨點對不上，替換不會生效：\n{old[:60]}...")
    return text.replace(old, new)

# 餵給模型的互動紀錄筆數上限。
#
# 只取最近幾筆，不是為了省錢，是因為跟進建議的依據本來就是「最近發生什麼」。
# 把半年前的紀錄一起丟進去，模型反而容易挑到過期的細節來當話術開場，
# 那比少講一句更糟 —— 業務照著講會顯得他根本沒在跟。
MAX_INTERACTIONS = 5

SYSTEM_PROMPT_V1 = """你是台灣房仲公司的資深業務主管，正在指導手下的業務跟進一位客戶。

你會拿到這位客戶的資料、系統算出的意願分數、跟進狀態，以及最近的互動紀錄。
你的工作是給出**下一步具體該怎麼做**。

請輸出三段：

【next_action 下一步動作】
一句話講清楚業務接下來該做什麼，要是一個具體動作。
好的例子：「致電確認上週看的物件他考慮得如何」
壞的例子：「持續追蹤」「保持聯繫」——這種話等於沒說。

【talking_point 建議話術】
業務可以直接照著講的開場，用第一人稱寫，像真人在講電話。
- 從客戶自己說過的事情切入，不要從「我這邊有物件」開始
- 台灣房仲的口語，不要書面語，不要用「您好，敝公司」這種生硬的說法
- 一段就好，不要條列

【suggested_timing 建議時機】
什麼時候聯絡比較好，例如「今天下班前」「明天上午」「這週六」。
如果客戶講過他方便的時間，就照他講的。

【evidence 引用依據】
把你在話術裡用到的客戶資訊，**逐字**從「客戶原話」或「互動紀錄」裡摘出來。
- 一定要是原文的連續片段，不可以改寫、不可以濃縮、不可以自己接兩段話
- 最多 5 條，沒有引用任何客戶資訊就給空陣列
- 這一欄會被程式逐字比對，改寫過的句子會被判定為捏造

## 最重要的一條規則

**只能講輸入裡有的事實。**

不要編造客戶沒說過的話、不要假設他的職業或家庭狀況、
不要提到任何一個輸入裡沒有出現的物件、路名、建案或價格。
資訊不夠時，正確的做法是建議業務去問，而不是自己補一個聽起來合理的細節。

CRM 裡出現客戶從沒說過的資訊，比話術寫得平淡嚴重得多 ——
業務照著一句捏造的話打過去，客戶當場就知道他沒在聽。
"""

# v2 只補字數限制。
#
# v1 第一次真的連上模型就有一筆失敗：它把整串需求塞進「下一步動作」寫了 65 個字，
# 超過 schema 的 60 字上限，整則建議被 Pydantic 擋下來作廢。
#
# 根因不是模型笨，是**限制只寫在程式裡，沒寫進 prompt**——
# 跟 Sprint 4 的 v1→v2 是同一個病（區域的認定規則在標註標準裡有，卻沒告訴模型）。
#
# 順便講清楚「下一步只講一個動作」。那筆失敗的輸出其實有兩個問題，
# 長度只是表徵：它把「確認同社區還有沒有別的戶別」跟「重述客戶的所有條件」
# 揉成一句話。業務看到那種句子不知道要先做哪一件。
#
# 給的數字都比程式的上限留了餘裕（25 字 vs 60、150 字 vs 300），
# 這樣模型偶爾寫超過一點也不會整則作廢——
# 驗證是安全網，不該是常態的失敗來源。
SYSTEM_PROMPT_V2 = _revise(
    _revise(
        _revise(
            SYSTEM_PROMPT_V1,
            """【next_action 下一步動作】
一句話講清楚業務接下來該做什麼，要是一個具體動作。
好的例子：「致電確認上週看的物件他考慮得如何」
壞的例子：「持續追蹤」「保持聯繫」——這種話等於沒說。""",
        """【next_action 下一步動作】**25 字以內**
一句話講清楚業務接下來該做什麼，要是一個具體動作。
好的例子：「致電確認上週看的物件他考慮得如何」
壞的例子：「持續追蹤」「保持聯繫」——這種話等於沒說。

**只講一個動作。** 不要在這裡重述客戶的條件，也不要把兩三件事串成一句。
業務要能看完就知道現在該做哪一件事，條件寫在話術裡就好。""",
        ),
        """業務可以直接照著講的開場，用第一人稱寫，像真人在講電話。""",
        """**150 字以內。**
業務可以直接照著講的開場，用第一人稱寫，像真人在講電話。""",
    ),
    """什麼時候聯絡比較好，例如「今天下班前」「明天上午」「這週六」。""",
    """**15 字以內。**
什麼時候聯絡比較好，例如「今天下班前」「明天上午」「這週六」。""",
)

FOLLOW_UP_PROMPT_V2 = "follow_up_v2"

# v3 修的是 v2 唯一那一類真正的錯誤。
#
# v2 在 11 筆有效案例上，引用有出處只有 81.8%。看兩個失敗案例的內容，
# 錯的不是模型的理解，是**它抄了我排版時加上去的字**：
#
#   fu-007 引用了「區域：三重」「預算：1200 萬（客戶講的是概數）」
#          —— 那是 context 裡【客戶資料】那一段，我用「欄位：值」印出來的。
#          客戶講的原話是「先了解一下三重的行情」。
#   fu-009 引用了「2026-01-09 電話：致電未接」
#          —— 內容確實是互動紀錄，但日期跟管道是我加的前綴。
#
# 也就是說：模型並沒有捏造任何事實，它引用的每一件事客戶都真的說過，
# 只是它把「我整理過的樣子」當成了原話。
#
# 這件事在 v1、v2 的 prompt 裡從來沒被交代過 —— 我只說了「逐字摘出來」，
# 卻沒說「從哪裡摘」。又是同一個病：規則存在於程式裡（build_source_text
# 只收客戶原話與互動內容），沒有寫進 prompt。
#
# 這也說明為什麼 evidence 這個機制值得留：它把一個原本要靠人讀完
# 十二段話術才發現的問題，變成兩行明確的失敗訊息。
SYSTEM_PROMPT_V3 = _revise(
    SYSTEM_PROMPT_V2,
    """【evidence 引用依據】
把你在話術裡用到的客戶資訊，**逐字**從「客戶原話」或「互動紀錄」裡摘出來。
- 一定要是原文的連續片段，不可以改寫、不可以濃縮、不可以自己接兩段話
- 最多 5 條，沒有引用任何客戶資訊就給空陣列
- 這一欄會被程式逐字比對，改寫過的句子會被判定為捏造""",
    """【evidence 引用依據】
把你在話術裡用到的客戶資訊，**逐字**摘出來。

**只能從這兩個地方摘：**
1. 【客戶原話】那一段的文字
2. 【最近的互動紀錄】每一行**冒號後面**的內容

**不可以從這些地方摘：**
- 【客戶資料】那一段（「區域：三重」「預算：1200 萬」那種）
  —— 那是系統整理過的欄位，不是客戶講的話
- 【系統評分】【跟進狀態】那兩段
- 互動紀錄開頭的日期與管道
  —— 「2026-01-09 電話：致電未接」要摘的是「致電未接」，
     日期跟「電話」是系統加的，客戶沒有講過那幾個字

其他規則：
- 一定要是原文的連續片段，不可以改寫、不可以濃縮、不可以自己接兩段話
- 最多 5 條，沒有引用任何客戶資訊就給空陣列
- 這一欄會被程式逐字比對，摘錯地方會被判定為捏造""",
)

FOLLOW_UP_PROMPT_V3 = "follow_up_v3"

# v4 補的是一條**業務實務規則**，不是格式問題。
#
# v3 在開發集上四條判準全過，但有一筆錯得很明顯，而四條判準全都看不到：
#
#   客戶說：叫我下週三下午再打給她
#   建議時機：今天下午
#
# 它引用得完全正確（那句話逐字摘出來了），grounding 判 PASS，
# 然後建議業務今天就打。前面那幾條檢查的是「有沒有亂講」，
# 沒有一條在問「講得對不對」。
#
# 這條規則是專案作者（有房仲業務經驗）定的：
# 客戶掛電話前講的那句「X 再打給我」，是他給的最明確的指示。
# 業務提早打過去，等於沒把他的話當一回事。
#
# 對應的判準是 evaluation/followup_criteria.check_timing_matches_appointment。
# 規則要同時寫進 prompt 與判準——只寫判準是抓錯不修錯，
# 只寫 prompt 則沒有人在驗它有沒有照做。
SYSTEM_PROMPT_V4 = _revise(
    SYSTEM_PROMPT_V3,
    """**15 字以內。**
什麼時候聯絡比較好，例如「今天下班前」「明天上午」「這週六」。
如果客戶講過他方便的時間，就照他講的。""",
    """**15 字以內。**
什麼時候聯絡比較好，例如「今天下班前」「明天上午」「這週六」。

**客戶自己約過時間的話，一律照他講的，不可以提前。**
- 「叫我下週三下午再打給你」→ 建議時機就是「下週三下午」，不是「今天下午」
- 「我下週回你」→ 建議時機是「下週」
客戶掛電話前講的那句話，是他給的最明確的指示。
提早打過去等於沒把他的話當一回事，客戶會直接感覺到。

**「有空」「方便」這種話要看前後文在講什麼**，同一句話意思可能完全相反：
- 「電話的話我只有週六下午有空」→ 講的是**聯絡時間**，建議時機就照它
- 「約週末看屋，我只有週六下午有空」→ 講的是**看屋時間**，
  不是叫你週六才能打電話。要打電話確認事情，不必等到那時候。
- 看不出來在講哪一種時，就當成沒有約定，自己判斷合適的時機。

另外，**已經約好帶看的客戶，帶看前一天要先聯絡確認**。
客戶臨時有事卻沒講，業務白跑一趟；先確認一次，也是再接觸一次的機會。""",
)

FOLLOW_UP_PROMPT_V4 = "follow_up_v4"

FOLLOW_UP_PROMPTS: dict[str, str] = {
    FOLLOW_UP_PROMPT_V1: SYSTEM_PROMPT_V1,
    FOLLOW_UP_PROMPT_V2: SYSTEM_PROMPT_V2,
    FOLLOW_UP_PROMPT_V3: SYSTEM_PROMPT_V3,
    FOLLOW_UP_PROMPT_V4: SYSTEM_PROMPT_V4,
}

DEFAULT_FOLLOW_UP_PROMPT_VERSION = FOLLOW_UP_PROMPT_V4

FOLLOW_UP_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "next_action": {"type": "string"},
        "talking_point": {"type": "string"},
        "suggested_timing": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["next_action", "talking_point", "suggested_timing", "evidence"],
}


# ----------------------------------------------------------------------
# 組 context
# ----------------------------------------------------------------------

_PROPERTY_TYPE_LABELS = {
    "ELEVATOR_BUILDING": "電梯大樓",
    "LOW_RISE": "華廈",
    "APARTMENT": "公寓",
    "TOWNHOUSE": "透天厝",
    "VILLA": "別墅",
    "STUDIO": "套房",
}

_PURPOSE_LABELS = {
    "SELF_USE": "自住",
    "INVESTMENT": "投資",
    "BOTH": "自住兼投資",
    "UNKNOWN": "未確定",
}

_INTERACTION_LABELS = {
    "CALL": "電話",
    "LINE": "LINE",
    "EMAIL": "Email",
    "MEETING": "面談",
    "VIEWING": "帶看",
    "NOTE": "備註",
}


def _format_budget(lead: Lead) -> str | None:
    """把預算寫成人看得懂的樣子，並且保留「概數」這個語氣。

    直接把 20000000 丟給模型，它有時會在話術裡寫成「兩千萬整」，
    但客戶說的是「2000 萬左右」—— 那是兩件不同的事，
    而且正是 Sprint 5 用來判斷他還在不在觀望的訊號。
    """
    if lead.budget_max is None and lead.budget_min is None:
        return None

    def to_wan(value: int) -> str:
        return f"{value // 10000} 萬"

    if lead.budget_min is not None and lead.budget_max is not None:
        text = f"{to_wan(lead.budget_min)}～{to_wan(lead.budget_max)}"
    else:
        text = to_wan(lead.budget_max if lead.budget_max is not None else lead.budget_min)

    return f"{text}（客戶講的是概數）" if lead.budget_is_approximate else text


def build_source_text(lead: Lead, interactions: list[Interaction]) -> str:
    """組出「客戶說過的話」，也就是 evidence 唯一合法的來源。

    刻意**不包含**結構化欄位（location、budget…）。
    那些是 AI 解析出來的二手資料，不是客戶的原話 ——
    若允許從那裡引用，「引用逐字原文」這個檢查就會失去意義：
    模型可以引用一個它自己在上一步抽出來的詞，然後宣稱有出處。
    """
    parts = [lead.raw_requirement or ""]
    parts.extend(i.content or "" for i in interactions)
    return "\n".join(p for p in parts if p)


def build_context(
    lead: Lead,
    interactions: list[Interaction],
    score: ScoreResult,
    status: follow_up.FollowUpStatus,
    today: date,
) -> str:
    """把一位客戶的現況寫成餵給模型的文字。

    這個函式是純函式，沒有 IO —— 所以「context 有沒有帶到互動紀錄」
    這件事可以直接測，不必真的呼叫模型。
    """
    lines: list[str] = [f"今天是 {today.isoformat()}。", "", "【客戶資料】", f"姓名：{lead.name}"]

    fields: list[tuple[str, str | None]] = [
        ("區域", lead.location),
        ("預算", _format_budget(lead)),
        ("房數", f"{lead.rooms} 房" if lead.rooms is not None else None),
        (
            "房屋類型",
            _PROPERTY_TYPE_LABELS.get(lead.property_type.value) if lead.property_type else None,
        ),
        (
            "屋齡上限",
            f"{lead.building_age_max} 年" if lead.building_age_max is not None else None,
        ),
        ("車位", None if lead.parking is None else ("需要" if lead.parking else "不需要")),
        ("購屋目的", _PURPOSE_LABELS.get(lead.purpose.value) if lead.purpose else None),
        (
            "購屋時程",
            f"{lead.purchase_timeline} 個月內" if lead.purchase_timeline is not None else None,
        ),
    ]
    # 沒有的欄位整行不印，而不是印「未提供」。
    # 印出一堆「未提供」會讓模型把注意力放在缺什麼，
    # 然後話術就變成一連串盤問客戶的問題。
    lines.extend(f"{label}：{value}" for label, value in fields if value)

    if lead.urgency is not None:
        lines.append("急迫程度：客戶明確表達急" if lead.urgency.value == "HIGH" else "急迫程度：客戶說不急")

    lines.append(f"目前狀態：{lead.status.value}")

    # 已經約好的帶看時間。
    #
    # 這一行看起來多餘（下面的【跟進狀態】也會提到「明天帶看」），
    # 但那句話只在**前一天**才會出現。帶看還有三天時，
    # 沒有這一行的話模型完全不知道這個約存在，
    # 於是它會建議一個跟那個約無關、甚至撞在一起的下一步。
    if lead.viewing_scheduled_at is not None:
        lines.append(
            f"已約帶看：{lead.viewing_scheduled_at.strftime('%Y-%m-%d %H:%M')}"
        )

    # 分數與理由都是 Rule Engine 算好的，模型只是拿來當背景，不需要自己判斷。
    lines += [
        "",
        "【系統評分】",
        f"意願分數：{score.score} 分（{score.level.value}）",
        "評分理由：" + "、".join(f"{r.label} {r.points:+d}" for r in score.reasons)
        if score.reasons
        else "評分理由：（無，客戶資料太少）",
        "",
        "【跟進狀態】",
        status.reason,
    ]

    lines += ["", "【客戶原話】", lead.raw_requirement or "（業務尚未記錄客戶原始需求）"]

    lines += ["", f"【最近的互動紀錄（最多 {MAX_INTERACTIONS} 筆，由新到舊）】"]
    if interactions:
        lines.extend(
            f"- {i.created_at.date().isoformat()} {_INTERACTION_LABELS.get(i.type.value, i.type.value)}：{i.content}"
            for i in interactions
        )
    else:
        lines.append("（還沒有任何互動紀錄，這是第一次聯絡）")

    return "\n".join(lines)


# ----------------------------------------------------------------------
# 捏造檢查
# ----------------------------------------------------------------------


def _normalize(text: str) -> str:
    """比對前先把空白全部拿掉。

    模型偶爾會把「三房 兩廳」的空白吃掉或多加一個，
    那不是捏造，只是排版差異，不該被算成捏造。
    除此之外不做任何寬鬆處理 —— 標點、用字都必須一模一樣，
    否則這個檢查就從「逐字引用」滑成「意思差不多」，那就沒有守住任何東西了。
    """
    return "".join(text.split())


def verify_evidence(evidence: list[str], source_text: str) -> tuple[list[str], list[str]]:
    """把 evidence 分成「有出處」與「沒出處」兩堆。

    這是整個功能唯一一個確定性的品質檢查，也是 Criteria-based 評估
    最主要的一項指標。回傳兩個清單而不是一個布林值，
    是因為評估要算的是「幾條裡有幾條沒出處」，不是「有沒有問題」。
    """
    normalized_source = _normalize(source_text)
    grounded, ungrounded = [], []
    for quote in evidence:
        target = grounded if _normalize(quote) and _normalize(quote) in normalized_source else ungrounded
        target.append(quote)
    return grounded, ungrounded


def compose_text(suggestion: FollowUpSuggestion) -> str:
    """把三段組成一段純文字，存進 ai_analysis.suggestion。

    存這一欄不是為了畫面（畫面用結構化的三段各自渲染），
    是為了 Sprint 8 的 n8n：它要把建議寄到業務信箱，
    在那邊再拼一次字串等於同一份格式維護兩遍。
    """
    return (
        f"下一步：{suggestion.next_action}\n"
        f"建議時機：{suggestion.suggested_timing}\n"
        f"建議話術：{suggestion.talking_point}"
    )


@dataclass(frozen=True)
class FollowUpOutcome:
    """一次建議的完整結果，加上要存進 ai_analysis 的後設資料。"""

    suggestion: FollowUpSuggestion
    # 模型給了但比對不到出處的引用。留著給評估統計用，不回給前端。
    ungrounded_evidence: list[str]
    context: str
    model: str
    prompt_version: str
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int


class FollowUpAdvisor:
    def __init__(
        self,
        provider: LLMProvider,
        prompt_version: str = DEFAULT_FOLLOW_UP_PROMPT_VERSION,
    ):
        self.provider = provider
        if prompt_version not in FOLLOW_UP_PROMPTS:
            raise ValueError(f"未知的 follow-up prompt 版本：{prompt_version}")
        self.prompt_version = prompt_version

    def suggest(
        self,
        lead: Lead,
        interactions: list[Interaction],
        score: ScoreResult,
        status: follow_up.FollowUpStatus,
        today: date,
    ) -> FollowUpOutcome:
        recent = interactions[:MAX_INTERACTIONS]
        context = build_context(lead, recent, score, status, today)
        started = time.perf_counter()

        try:
            response = self.provider.complete_json(
                system_prompt=FOLLOW_UP_PROMPTS[self.prompt_version],
                user_prompt=context,
                schema_name="follow_up_suggestion",
                json_schema=FOLLOW_UP_JSON_SCHEMA,
            )
        except LLMError as exc:
            logger.warning("跟進建議呼叫 LLM 失敗：%s", exc)
            raise AIServiceError() from exc

        latency_ms = int((time.perf_counter() - started) * 1000)

        try:
            suggestion = FollowUpSuggestion.model_validate(json.loads(response.content))
        except (json.JSONDecodeError, PydanticValidationError) as exc:
            logger.warning(
                "跟進建議未通過驗證：%s | 原始內容=%s", exc, response.content
            )
            raise AIServiceError("AI 回傳的內容不符合預期格式，請再試一次") from exc

        grounded, ungrounded = verify_evidence(
            suggestion.evidence, build_source_text(lead, recent)
        )
        if ungrounded:
            # 比對不到出處的引用直接拿掉，不顯示給業務。
            #
            # 為什麼不是整則建議退回：一條引用比對失敗，多半是模型把兩句話接在一起
            # 或改了個標點，退掉整則會讓功能在正常情況下也常常失敗。
            # 但把一句「客戶說過的話」原封不動秀給業務，代價高得多 ——
            # 業務會直接照著念。所以折衷是：拿掉，記錄下來，留給評估去統計。
            #
            # 這**不等於**保證話術本身沒有捏造，話術裡的捏造只有評估抓得到。
            # 這正是為什麼這個功能一定要有 Criteria-based 評估。
            logger.warning(
                "Lead %s 的跟進建議有 %d 條引用找不到出處：%s",
                lead.id,
                len(ungrounded),
                ungrounded,
            )
            suggestion = suggestion.model_copy(update={"evidence": grounded})

        logger.info(
            "跟進建議完成 lead=%s model=%s prompt_version=%s latency=%sms tokens=%s/%s",
            lead.id,
            response.model,
            self.prompt_version,
            latency_ms,
            response.prompt_tokens,
            response.completion_tokens,
        )

        return FollowUpOutcome(
            suggestion=suggestion,
            ungrounded_evidence=ungrounded,
            context=context,
            model=response.model,
            prompt_version=self.prompt_version,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            latency_ms=latency_ms,
        )
