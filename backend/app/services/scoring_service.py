"""Lead Scoring：deterministic Rule Engine。

**這裡沒有 LLM，一行都沒有。**

這是整個專案最重要的一條分界線，也是面試時最值得講的一段：
相同的資料永遠得到相同的分數，因為它是規則不是模型。

為什麼堅持不用 LLM 算分：

1. **可解釋**：業務問「為什麼這個客戶是 65 分」，答案是一張逐條列出的清單，
   不是「模型覺得」。
2. **可稽核**：分數會影響業務今天先打給誰。一個無法解釋的排序，
   沒有人敢照著做。
3. **可重現**：同一筆資料今天跑跟明天跑一定一樣。LLM 做不到這件事。

AI 的角色是**把非結構化的原話變成結構化欄位**（Sprint 3），
到此為止。欄位變成分數這一段，是純粹的規則。

---

計分只看**客戶本身**，不看業務做了多少事：

    需求明確度  55   他到底想要什麼，說得多清楚
    聯絡方式    10   找不找得到他
    購買時機    35   現在買，還是明年再說

### 為什麼互動紀錄不計分

一度把「帶看過」算進分數裡，後來拿掉了，理由是**那對新客戶不公平**：
剛填完表單的客戶，不管條件多好，那幾分都是結構性拿不到的。
一個拿不到滿分的族群跟一個拿得到的族群，分數就不能互相比較，
而「不能互相比較的分數」拿來排序是危險的。

拿掉之後，一個剛進來、需求寫得清楚又很急的新客戶可以拿到 100 分 ——
這正是業務最該立刻打電話的那種人。

「跟進到哪一步了」是另一個問題，由 Need Follow-up 回答（見 follow_up.py），
兩件事分開算，各自才講得清楚。

滿分制而不是無上限累加，是為了讓分數之間可以互相比較 ——
「65 分」要能一眼看出是「拿到三分之二」，而不是一個沒有基準的數字。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.enums import LeadLevel, Urgency
from app.models.lead import Lead

# --- 需求明確度（滿分 55）---
POINTS_BUDGET_EXACT = 20
# 「2000 萬左右」的客戶通常還在觀望，跟「就是 2000 萬」的購買意願有差。
# budget_is_approximate 這個欄位當初在 Sprint 3 建立，就是為了這一刻。
POINTS_BUDGET_APPROXIMATE = 10
POINTS_LOCATION = 15
POINTS_PROPERTY = 15
POINTS_PURPOSE = 5

# --- 聯絡方式（滿分 10）---
POINTS_PHONE = 10

# --- 購買時機（滿分 35）---
# 時機是單項權重最高的，因為在房仲實務上它決定了「現在投入有沒有用」。
URGENT_MONTHS = 3
MID_TERM_MONTHS = 12
POINTS_TIMING_URGENT = 35
POINTS_TIMING_MID = 10
# 「客戶說不急」是資訊，「客戶沒講」是沒有資訊，兩者不該同分。
# 已知的冷客戶應該排在未知客戶的後面 —— 沒講的那位，說不定其實很急。
PENALTY_TIMING_COLD = -10

# --- 分級門檻 ---
#
# HOT 一度設在 60，但在 20 筆 Demo 資料上跑出來 74% 的客戶都是「高意願」——
# 當三個裡有兩個都是 HOT，這個標籤就失去意義了，它的用途是「先打這幾通」。
#
# 分數分佈解釋了原因：有時間壓力的落在 90～100，需求填得完整但沒有時間訊號的
# 整群卡在 65。60 這個門檻等於「需求填得完整就算高意願」。
# 拉到 70 之後，HOT 剛好等於「需求完整 + 有時間壓力」。
HOT_THRESHOLD = 70
WARM_THRESHOLD = 30


@dataclass(frozen=True)
class ScoreReason:
    """一條計分理由。

    code 給程式用（前端據此上色、日後做統計），
    label 給人看，points 是這條加了或扣了幾分。
    """

    code: str
    label: str
    points: int


@dataclass(frozen=True)
class ScoreResult:
    score: int
    level: LeadLevel
    reasons: list[ScoreReason]


def _requirement_reasons(lead: Lead) -> list[ScoreReason]:
    """需求明確度：他到底想要什麼，說得多清楚。"""
    reasons: list[ScoreReason] = []

    if lead.budget_max is not None or lead.budget_min is not None:
        if lead.budget_is_approximate:
            reasons.append(
                ScoreReason(
                    "budget_approximate",
                    "有預算但講的是概數",
                    POINTS_BUDGET_APPROXIMATE,
                )
            )
        else:
            reasons.append(
                ScoreReason("budget_exact", "預算明確", POINTS_BUDGET_EXACT)
            )

    if lead.location:
        reasons.append(ScoreReason("location", "區域明確", POINTS_LOCATION))

    # 房數或房屋類型，有一個就算講清楚了房型
    if lead.rooms is not None or lead.property_type is not None:
        reasons.append(ScoreReason("property", "房型明確", POINTS_PROPERTY))

    if lead.purpose is not None:
        reasons.append(ScoreReason("purpose", "購屋目的明確", POINTS_PURPOSE))

    return reasons


def _contact_reasons(lead: Lead) -> list[ScoreReason]:
    """聯絡方式：找不找得到他。"""
    if lead.phone:
        return [ScoreReason("phone", "有留電話", POINTS_PHONE)]
    return []


def _timing_reasons(lead: Lead) -> list[ScoreReason]:
    """購買時機：現在買，還是明年再說。

    這一段刻意同時看兩個欄位。真實客戶很少會講「我三個月內要買到房子」，
    但常常講「有點急」—— 只看 purchase_timeline 的話，
    那種客戶會被當成沒有時間壓力，排到不該排的位置。
    """
    months = lead.purchase_timeline

    if months is not None and months <= URGENT_MONTHS:
        return [ScoreReason("timing_urgent", f"{months} 個月內要買", POINTS_TIMING_URGENT)]

    if lead.urgency is Urgency.HIGH:
        return [ScoreReason("timing_urgent", "客戶表達急迫", POINTS_TIMING_URGENT)]

    # 說不急，或講的期程超過一年 —— 兩者都代表短期內不會成交。
    # 一年半跟兩年在業務動作上沒有差別，所以不必區分得更細。
    if lead.urgency is Urgency.LOW or (
        months is not None and months > MID_TERM_MONTHS
    ):
        return [ScoreReason("timing_cold", "短期內沒有購買打算", PENALTY_TIMING_COLD)]

    if months is not None:
        return [ScoreReason("timing_mid", f"{months} 個月內要買", POINTS_TIMING_MID)]

    return []


def level_for_score(score: int) -> LeadLevel:
    """分數換算成等級。

    抽成獨立函式是為了能直接測門檻 —— 邊界值最容易寫反（>= 寫成 >），
    而寫反了畫面上看不出來，只是有些客戶莫名其妙少一級。
    """
    if score >= HOT_THRESHOLD:
        return LeadLevel.HOT
    if score >= WARM_THRESHOLD:
        return LeadLevel.WARM
    return LeadLevel.COLD


def calculate_score(lead: Lead) -> ScoreResult:
    """算出這位客戶的分數、等級與逐條理由。

    參數只有 lead，沒有 interactions —— 這個簽名本身就是設計聲明：
    Lead Score 只看客戶本身，不看業務做了多少事。

    純函式：同樣的輸入永遠得到同樣的輸出，不碰資料庫也不碰網路。
    所以它的測試不需要任何 mock。
    """
    reasons = [
        *_requirement_reasons(lead),
        *_contact_reasons(lead),
        *_timing_reasons(lead),
    ]

    # 下限卡在 0：條件齊全但說不急的客戶，仍然該比什麼都沒講的客戶有價值。
    # 讓分數變成負的只會讓畫面難讀，並不會讓排序更正確。
    score = max(0, sum(r.points for r in reasons))

    return ScoreResult(score=score, level=level_for_score(score), reasons=reasons)
