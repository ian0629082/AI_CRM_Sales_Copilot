"""Need Follow-up：今天該聯絡誰。

跟 Lead Score 分開，因為兩者回答的是不同的問題：

    Lead Score       這個客戶值不值得投入？   ← 看客戶本身
    Need Follow-up   我今天該打給誰？         ← 看多久沒動了

一開始想把兩者合成一個分數，但那會讓新客戶跟跟進中的客戶無法比較 ——
新客戶不管條件多好，「已帶看」那幾分都是結構性拿不到的。

---

## 提醒時間由誰決定

**業務自己填，系統只給預設值。**

一度想寫一整張規則表（議價 2 天、帶看 1 天、說不急 14 天⋯⋯），
但業務知道的比規則多：客戶掛電話前說「我下週三再回你」，
業務填 7 天就對了，任何規則都猜不到那句話。

所以規則從「決定」降級成「建議的預設值」：
記錄互動時自動帶一個天數，業務隨時可以改。
規則猜錯的時候，業務直接覆蓋，不必跟系統對抗。

唯一由系統決定的是**第一次聯絡**：客戶剛填完表單，業務還沒碰過他，
根本沒有機會設提醒 —— 這時候只能由系統盯著。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

from app.models.enums import InteractionType, LeadStatus
from app.models.interaction import Interaction
from app.models.lead import Lead

# 記錄互動時「下次提醒」欄位帶的預設值，業務可以改。
DEFAULT_FOLLOW_UP_DAYS: dict[InteractionType, int] = {
    InteractionType.VIEWING: 1,  # 帶看完是最熱的時候，不能讓它冷掉
    InteractionType.MEETING: 2,
    InteractionType.CALL: 3,
    InteractionType.LINE: 3,
    InteractionType.EMAIL: 3,
    # 備註預設隔天再提醒。
    #
    # 「備註」是個大雜燴：可能是「致電未接」，也可能是「客戶說下週回覆」。
    # 系統分不出來，所以往保守的方向猜 —— 假設還沒聯絡上，隔天再試一次。
    # 漏掉一個沒接通的客戶，代價比多提醒一次大得多。
    # 業務知道不用那麼急，自己改成 7 天就好。
    InteractionType.NOTE: 1,
}

# 客戶建檔後多久沒被聯絡就進「新進未聯絡」清單。
# 房仲實務上第一時間回應的轉換率差很多，所以這個值很短。
NEW_LEAD_GRACE_DAYS = 1

# 已經結案的客戶不需要跟進提醒
CLOSED_STATUSES = frozenset({LeadStatus.WON, LeadStatus.LOST})


class FollowUpBucket(str, Enum):
    """這位客戶現在屬於哪一堆。

    「新進未聯絡」與「到期跟進」刻意分成兩堆，不混在一起 ——
    它們對應兩種不同的業務動作：一個是「第一次接觸」，一個是「維繫」。
    混在一起的話，業務打開清單看到 20 個人，
    不知道哪些是還沒認識、哪些是快跑掉了。
    """

    NEW_UNCONTACTED = "NEW_UNCONTACTED"  # 客戶填了表，還沒有人聯絡過他
    DUE = "DUE"  # 業務設的提醒日到了
    SCHEDULED = "SCHEDULED"  # 有提醒日，但還沒到
    MUTED = "MUTED"  # 業務明確關掉了提醒
    CLOSED = "CLOSED"  # 成交或流失


@dataclass(frozen=True)
class FollowUpStatus:
    bucket: FollowUpBucket
    # 逾期幾天。用來排序：拖越久的排越前面。
    days_overdue: int
    reason: str

    @property
    def needs_attention(self) -> bool:
        return self.bucket in (FollowUpBucket.NEW_UNCONTACTED, FollowUpBucket.DUE)


def default_follow_up_days(interaction_type: InteractionType) -> int:
    return DEFAULT_FOLLOW_UP_DAYS.get(interaction_type, 3)


def evaluate(
    lead: Lead, interactions: list[Interaction], today: date
) -> FollowUpStatus:
    """判斷這位客戶今天需不需要被聯絡。

    today 由呼叫端傳入而不是在裡面呼叫 date.today()，
    這樣測試才能自由地移動時間，不必去 mock 系統時鐘。
    """
    if lead.status in CLOSED_STATUSES:
        return FollowUpStatus(FollowUpBucket.CLOSED, 0, "已結案")

    # 靜音要排在所有判斷之前。
    # 業務明確說了「不用提醒」，系統就不該再有任何意見 ——
    # 一份會冒出你關過的人的待辦清單，沒有人敢信。
    if lead.follow_up_muted:
        return FollowUpStatus(FollowUpBucket.MUTED, 0, "已關閉提醒")

    if not interactions:
        # 客戶填了表但還沒有人碰過他。這時業務沒有機會設提醒，只能由系統盯。
        waiting = (today - lead.created_at.date()).days
        overdue = waiting - NEW_LEAD_GRACE_DAYS
        if overdue >= 0:
            return FollowUpStatus(
                FollowUpBucket.NEW_UNCONTACTED,
                overdue,
                f"建檔 {waiting} 天，還沒有人聯絡過",
            )
        return FollowUpStatus(FollowUpBucket.SCHEDULED, 0, "今天剛建檔")

    if lead.next_follow_up_at is None:
        # 聯絡過卻沒有提醒日，代表資料不完整（多半是舊資料）。
        # 往「提醒」的方向倒，不要讓客戶安靜地消失。
        return FollowUpStatus(FollowUpBucket.DUE, 0, "沒有設定下次提醒時間")

    overdue = (today - lead.next_follow_up_at).days
    if overdue >= 0:
        return FollowUpStatus(
            FollowUpBucket.DUE,
            overdue,
            "今天該聯絡" if overdue == 0 else f"已逾期 {overdue} 天",
        )

    return FollowUpStatus(
        FollowUpBucket.SCHEDULED, 0, f"{lead.next_follow_up_at} 再聯絡"
    )
