"""註冊時自動建立的範例客戶。

## 為什麼要這個

新帳號進去是全空的：客戶列表沒東西、Dashboard 全是零、漏斗沒有形狀。
一個空的系統看不出它在做什麼 —— 使用者不知道 Lead Score 長什麼樣、
不知道跟進建議要按哪裡，也不知道自己該先做什麼。

這幾筆的目的是讓他**一進去就看得到系統在做什麼**，
而不是要他先想像出一個客戶再輸入。

## 跟 scripts/seed_demo.py 的差別

那支是給 demo 帳號用的，32 筆，目的是「每個功能都有東西可以展示」
（明天帶看、靜音、逾期、成交率的分子分母都要有）。

這裡只有 6 筆，目的不同：**讓人看懂**。所以挑的是分數高低分明、
狀態不同、一眼看得出差別的幾筆，多了反而變成要讀的東西。

兩邊的資料刻意分開寫，不是重複 —— 一份是展示的完整度，一份是理解的速度。

## 句子一樣不能重用評估資料集

跟 seed_demo 同一條紀律：這些句子會躺在資料庫裡被反覆分析，
重用測試句子的話，「從沒被用來調整過任何東西」這個前提會慢慢失效。
tests/test_evaluation_metrics.py 有一條測試同時守著兩邊。
"""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.enums import (
    InteractionType,
    LeadSource,
    LeadStatus,
    PropertyType,
    Purpose,
    Urgency,
)
from app.models.interaction import Interaction
from app.models.lead import Lead
from app.models.user import User
from app.services.scoring_service import calculate_score

# fmt: off
STARTER_LEADS: list[dict] = [
    # 高分、很急 —— 這一筆是要讓人看到「什麼樣的客戶會被排到最前面」
    dict(
        name="王振豪", phone="0987000001", source=LeadSource.WEB_FORM,
        status=LeadStatus.CONTACTED, created_days_ago=4,
        raw="南屯三房，預算2600萬，要有平面車位，公司三月要調過來所以想快點定下來",
        fields=dict(location="南屯", budget_max=26000000, rooms=3, parking=True,
                    purpose=Purpose.SELF_USE, purchase_timeline=2,
                    urgency=Urgency.HIGH),
        interactions=[(InteractionType.CALL, "電訪確認需求，客戶希望這週末就看房", 2)],
        follow_up=0,
    ),
    # 需求清楚但不急 —— 跟上面那筆對照，同樣資料完整，分數差在時間壓力
    dict(
        name="李佳穎", phone="0987000002", source=LeadSource.REFERRAL,
        status=LeadStatus.INTERESTED, created_days_ago=12,
        raw="想找北屯的兩房電梯大樓，1600萬以內，屋齡8年內，自住，明年再買就好",
        fields=dict(location="北屯", budget_max=16000000, rooms=2,
                    property_type=PropertyType.ELEVATOR_BUILDING,
                    building_age_max=8, purpose=Purpose.SELF_USE,
                    urgency=Urgency.LOW),
        interactions=[
            (InteractionType.CALL, "初次電訪，需求算清楚", 8),
            (InteractionType.LINE, "傳了兩間給客戶看", 4),
        ],
        follow_up=3,
    ),
    # 剛進來、還沒人聯絡 —— 讓「新進未聯絡」那一區有東西
    dict(
        name="陳彥廷", phone="0987000003", source=LeadSource.WEB_FORM,
        status=LeadStatus.NEW, created_days_ago=1,
        raw="網路留言想問西屯的房子，說預算大概2000萬，其他還沒講",
        fields=dict(location="西屯", budget_max=20000000,
                    budget_is_approximate=True),
        interactions=[], follow_up=None,
    ),
    # 明天要帶看 —— 讓「今天要打電話確認」那個提醒真的出現
    dict(
        name="蘇曉琪", phone="0987000004", source=LeadSource.LINE,
        status=LeadStatus.VIEWING, created_days_ago=21,
        raw="夫妻要換屋，想要四房，預算3000萬左右，小孩大了原本的房子不夠住",
        fields=dict(budget_max=30000000, budget_is_approximate=True, rooms=4,
                    purpose=Purpose.SELF_USE),
        interactions=[
            (InteractionType.VIEWING, "帶看兩間，客戶對其中一間格局滿意", 6),
            (InteractionType.CALL, "約好明天下午再看一次", 1),
        ],
        follow_up=None, viewing=(1, 14),
    ),
    # 逾期沒跟進 —— 讓待跟進清單有一筆是紅的
    dict(
        name="黃世明", phone="0987000005", source=LeadSource.PHONE,
        status=LeadStatus.INTERESTED, created_days_ago=28,
        raw="投資用的套房，800萬以內，靠近學校的最好，租得掉就好",
        fields=dict(budget_max=8000000, property_type=PropertyType.STUDIO,
                    purpose=Purpose.INVESTMENT),
        interactions=[(InteractionType.CALL, "聊過一次，客戶說再想想", 14)],
        follow_up=-6,
    ),
    # 成交 —— 讓漏斗有終點、成交率不是零
    dict(
        name="吳靜宜", phone="0987000006", source=LeadSource.WALK_IN,
        status=LeadStatus.WON, created_days_ago=65,
        raw="第一次買房，兩房就好，1400萬以內，希望離公司近一點",
        fields=dict(budget_max=14000000, rooms=2, purpose=Purpose.SELF_USE),
        interactions=[
            (InteractionType.VIEWING, "帶看三間", 40),
            (InteractionType.NOTE, "已簽約", 18),
        ],
        follow_up=None,
    ),
]
# fmt: on


def _utc(days_ago: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


def create_for(db: Session, owner: User) -> int:
    """替新註冊的使用者建立範例客戶。回傳建立的筆數。

    **不 commit**：由呼叫端跟註冊本身一起提交。
    這樣「使用者建好了但範例資料失敗」這種半套狀態不會存在。
    """
    today = date.today()

    for spec in STARTER_LEADS:
        lead = Lead(
            owner_id=owner.id,
            name=spec["name"],
            phone=spec["phone"],
            source=spec["source"],
            status=spec["status"],
            raw_requirement=spec["raw"],
            **spec["fields"],
        )

        follow_up = spec["follow_up"]
        if isinstance(follow_up, int):
            lead.next_follow_up_at = today + timedelta(days=follow_up)

        viewing = spec.get("viewing")
        if viewing is not None:
            days, hour = viewing
            lead.viewing_scheduled_at = datetime.combine(
                today + timedelta(days=days),
                datetime.min.time().replace(hour=hour),
                tzinfo=timezone.utc,
            )

        # 分數由同一套規則算，不寫死 —— 否則調整權重之後，
        # 範例資料會跟系統的實際行為對不上，而那正是最會誤導新使用者的地方。
        result = calculate_score(lead)
        lead.lead_score = result.score
        lead.lead_level = result.level

        lead.created_at = _utc(spec["created_days_ago"])
        lead.updated_at = lead.created_at
        db.add(lead)
        db.flush()

        for type_, content, days_ago in spec["interactions"]:
            db.add(
                Interaction(
                    lead_id=lead.id,
                    type=type_,
                    content=content,
                    created_at=_utc(days_ago),
                )
            )

    return len(STARTER_LEADS)
