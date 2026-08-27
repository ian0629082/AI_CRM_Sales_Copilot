"""建立 Demo 用的虛構客戶資料。

用法（在 backend 目錄下）：
    python -m scripts.seed_demo              # 建立，若已有 demo 資料會提醒
    python -m scripts.seed_demo --reset      # 先清掉舊的再重建

## 為什麼需要這個

只有三筆客戶的 Dashboard 看起來很空：漏斗只有兩根、成交率是「—」、
待跟進清單一兩個人。面試官打開看不出系統在做什麼。

這批資料的目的是讓畫面**一打開就有東西看**：
漏斗有形狀、成交率有數字、待跟進清單有內容、分數有高有低。

## 這些句子跟評估資料集完全不重複

`evaluation/` 底下那三份（dataset / holdout / final_test）是拿來量準確率的，
其中 final_test 更是鎖到 Sprint 7 才開的期末考。

若把測試句子拿來當 Demo 資料，那些句子就會被反覆分析、被反覆看到答案，
「從沒被用來調整過任何東西」這個前提就會慢慢失效。

所以這裡的句子是另外寫的 —— 風格參考真實業務口吻（有廢話、有現況陳述、
有講到一半改口），但一句都沒有重用。
tests/test_evaluation_metrics.py 有一條測試在守這件事。
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone

from app.db.database import SessionLocal
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

DEMO_EMAIL = "demo@example.com"

# 用一個前綴標記這批資料，--reset 才知道該刪哪些，
# 不會誤刪使用者自己建的客戶。
DEMO_TAG = "[demo]"

# (type, 內容, 幾天前)
Interactions = list[tuple[InteractionType, str, int]]

# fmt: off
LEADS: list[dict] = [
    # ---------- 新客戶：還沒有人聯絡過 ----------
    dict(
        name="張淑芬", phone="0912345001", source=LeadSource.WEB_FORM,
        status=LeadStatus.NEW, created_days_ago=3,
        raw="網路留言：想看北屯機捷附近的三房，預算1500萬上下，先生在竹科上班平常不在家",
        fields=dict(location="北屯", budget_max=15000000, budget_is_approximate=True,
                    rooms=3, purpose=Purpose.SELF_USE),
        interactions=[], follow_up=None,
    ),
    dict(
        name="李承翰", phone="0912345002", source=LeadSource.WEB_FORM,
        status=LeadStatus.NEW, created_days_ago=2,
        raw="想找電梯大樓兩房，屋齡5年內，中山區，預算1800萬，越快越好我這邊有點趕",
        fields=dict(location="中山區", budget_max=18000000, rooms=2,
                    property_type=PropertyType.ELEVATOR_BUILDING, building_age_max=5,
                    urgency=Urgency.HIGH),
        interactions=[], follow_up=None,
    ),
    dict(
        name="陳建良", phone=None, source=LeadSource.PHONE,
        status=LeadStatus.NEW, created_days_ago=6,
        raw="電話裡只說想看看透天，其他都還沒講，說再約時間細談",
        fields=dict(property_type=PropertyType.TOWNHOUSE),
        interactions=[], follow_up=None,
    ),
    dict(
        name="吳美玲", phone="0912345004", source=LeadSource.REFERRAL,
        status=LeadStatus.NEW, created_days_ago=0,
        raw="朋友介紹的，說想在南屯換個大一點的，現在住兩房不夠，想要四房，預算3000萬以內",
        fields=dict(location="南屯", budget_max=30000000, rooms=4,
                    purpose=Purpose.SELF_USE),
        interactions=[], follow_up=None,
    ),

    # ---------- 已聯絡 ----------
    dict(
        name="林志偉", phone="0912345005", source=LeadSource.WALK_IN,
        status=LeadStatus.CONTACTED, created_days_ago=12,
        raw="西屯三房，預算2200萬，一定要平面車位，自住，三個月內想成交",
        fields=dict(location="西屯", budget_max=22000000, rooms=3, parking=True,
                    purpose=Purpose.SELF_USE, purchase_timeline=3, urgency=Urgency.HIGH),
        interactions=[(InteractionType.CALL, "電訪確認需求，客戶說週末有空看房", 5)],
        follow_up=-2,
    ),
    dict(
        name="黃雅琪", phone="0912345006", source=LeadSource.LINE,
        status=LeadStatus.CONTACTED, created_days_ago=9,
        raw="小套房投資用，600萬左右，逢甲那邊，之後想分租給學生",
        fields=dict(location="逢甲", budget_max=6000000, budget_is_approximate=True,
                    property_type=PropertyType.STUDIO, purpose=Purpose.INVESTMENT),
        interactions=[(InteractionType.LINE, "傳了三間物件資料，客戶說再看看", 3)],
        follow_up=1,
    ),
    dict(
        name="蔡明宏", phone="0912345007", source=LeadSource.PHONE,
        status=LeadStatus.CONTACTED, created_days_ago=8,
        raw="想買公寓自住，1200萬到1500萬，三重或蘆洲都可以，不要太高樓層",
        fields=dict(location="三重", budget_min=12000000, budget_max=15000000,
                    property_type=PropertyType.APARTMENT, purpose=Purpose.SELF_USE),
        interactions=[(InteractionType.CALL, "第一次通話，需求還算明確", 2)],
        follow_up=0,
    ),
    dict(
        name="周佩君", phone="0912345008", source=LeadSource.REFERRAL,
        status=LeadStatus.CONTACTED, created_days_ago=25,
        raw="不急，明年小孩上小學前搬就好，要學區內的三房，預算2500萬，有物件再通知我",
        fields=dict(budget_max=25000000, rooms=3, purpose=Purpose.SELF_USE,
                    urgency=Urgency.LOW),
        interactions=[(InteractionType.CALL, "客戶明確表示不急，請我有好物件再聯絡", 10)],
        # 業務主動關掉提醒：客戶自己說了不急，追太勤反效果
        follow_up="muted",
    ),

    # ---------- 有興趣 ----------
    dict(
        name="許文彬", phone="0912345009", source=LeadSource.WALK_IN,
        status=LeadStatus.INTERESTED, created_days_ago=18,
        raw="北屯四房，預算3500萬，屋齡10年內，家裡兩台車所以要兩個車位，自住",
        fields=dict(location="北屯", budget_max=35000000, rooms=4, building_age_max=10,
                    parking=True, purpose=Purpose.SELF_USE),
        interactions=[
            (InteractionType.CALL, "初次電訪，需求很明確", 12),
            (InteractionType.VIEWING, "帶看北屯兩間，客戶對其中一間有興趣", 4),
        ],
        follow_up=-1,
    ),
    dict(
        name="鄭雅文", phone="0912345010", source=LeadSource.WEB_FORM,
        status=LeadStatus.INTERESTED, created_days_ago=15,
        raw="南區兩房就好，1000萬以內，自住，屋齡不限但不要有漏水",
        fields=dict(location="南區", budget_max=10000000, rooms=2,
                    purpose=Purpose.SELF_USE),
        interactions=[
            (InteractionType.CALL, "電訪了解需求", 8),
            (InteractionType.LINE, "傳了兩間，客戶說想先看照片", 3),
        ],
        follow_up=3,
    ),
    dict(
        name="劉家豪", phone="0912345011", source=LeadSource.LINE,
        status=LeadStatus.INTERESTED, created_days_ago=20,
        raw="投資收租，套房，700萬上下，中興大學周邊，最好已經有租客的",
        fields=dict(location="中興大學", budget_max=7000000, budget_is_approximate=True,
                    property_type=PropertyType.STUDIO, purpose=Purpose.INVESTMENT),
        interactions=[
            (InteractionType.CALL, "聊了投報率，客戶還算積極", 9),
            (InteractionType.NOTE, "致電未接，改傳 LINE", 5),
        ],
        follow_up=-5,
    ),

    # ---------- 已約訪 ----------
    dict(
        name="楊淑惠", phone="0912345012", source=LeadSource.REFERRAL,
        status=LeadStatus.MEETING, created_days_ago=22,
        raw="七期電梯大樓三房，預算2800萬左右，自住，半年內想定下來",
        fields=dict(location="七期", budget_max=28000000, budget_is_approximate=True,
                    rooms=3, property_type=PropertyType.ELEVATOR_BUILDING,
                    purpose=Purpose.SELF_USE, purchase_timeline=6),
        interactions=[
            (InteractionType.CALL, "初次接觸", 15),
            (InteractionType.MEETING, "到店面談，確認需求與貸款條件", 2),
        ],
        follow_up=1,
    ),
    # ---------- 已帶看 ----------
    dict(
        name="王俊傑", phone="0912345013", source=LeadSource.WALK_IN,
        status=LeadStatus.VIEWING, created_days_ago=30,
        raw="想看西區華廈，四房，預算3200萬，屋齡15年內，太太希望有管理員",
        fields=dict(location="西區", budget_max=32000000, rooms=4,
                    property_type=PropertyType.LOW_RISE, building_age_max=15,
                    purpose=Purpose.SELF_USE),
        interactions=[
            (InteractionType.CALL, "電訪", 20),
            (InteractionType.VIEWING, "帶看西區三間", 8),
            (InteractionType.MEETING, "夫妻一起到店，討論其中兩間", 3),
        ],
        follow_up=0,
    ),
    dict(
        name="邱雅琴", phone="0912345020", source=LeadSource.LINE,
        status=LeadStatus.VIEWING, created_days_ago=16,
        raw="北屯三房，預算2000萬以內，屋齡10年內，先生開車要平面車位",
        fields=dict(location="北屯", budget_max=20000000, rooms=3,
                    building_age_max=10, parking=True,
                    purpose=Purpose.SELF_USE, urgency=Urgency.HIGH),
        interactions=[
            (InteractionType.LINE, "傳北屯四間給她，她挑了兩間想看", 6),
            (InteractionType.VIEWING, "帶看北屯兩間，喜歡其中一間但嫌坪數小一點", 4),
            (InteractionType.CALL, "約好再看同社區另一戶", 1),
        ],
        follow_up=3,
        # 明天下午三點帶看 —— Dashboard 上「今天要確認」那一區靠這筆才有東西
        viewing=(1, 15),
    ),

    # ---------- 議價中 ----------
    dict(
        name="賴淑貞", phone="0912345014", source=LeadSource.REFERRAL,
        status=LeadStatus.NEGOTIATING, created_days_ago=35,
        raw="北屯三房，2400萬，已經看中一間在談價，希望屋主可以再讓一點",
        fields=dict(location="北屯", budget_max=24000000, rooms=3, parking=True,
                    purpose=Purpose.SELF_USE, purchase_timeline=1, urgency=Urgency.HIGH),
        interactions=[
            (InteractionType.VIEWING, "帶看北屯四間", 20),
            (InteractionType.VIEWING, "客戶帶家人複看", 10),
            (InteractionType.MEETING, "出價 2350 萬，等屋主回覆", 4),
        ],
        follow_up=-3,
    ),
    dict(
        name="高志明", phone="0912345015", source=LeadSource.PHONE,
        status=LeadStatus.NEGOTIATING, created_days_ago=40,
        raw="南屯透天，預算4500萬，自住，一個月內要決定，公司調職時間卡得很緊",
        fields=dict(location="南屯", budget_max=45000000,
                    property_type=PropertyType.TOWNHOUSE, purpose=Purpose.SELF_USE,
                    purchase_timeline=1, urgency=Urgency.HIGH),
        interactions=[
            (InteractionType.CALL, "初次接觸，時間壓力大", 30),
            (InteractionType.VIEWING, "帶看南屯兩間透天", 12),
            (InteractionType.MEETING, "議價中，差 80 萬", 2),
        ],
        follow_up=1,
    ),

    # ---------- 成交 ----------
    dict(
        name="江美惠", phone="0912345016", source=LeadSource.WEB_FORM,
        status=LeadStatus.WON, created_days_ago=60,
        raw="西屯兩房，1600萬，自住，一個人住不用太大",
        fields=dict(location="西屯", budget_max=16000000, rooms=2,
                    purpose=Purpose.SELF_USE),
        interactions=[
            (InteractionType.VIEWING, "帶看三間", 45),
            (InteractionType.MEETING, "簽約", 30),
            (InteractionType.NOTE, "已完成交屋", 20),
        ],
        follow_up=None,
    ),
    dict(
        name="曾建華", phone="0912345017", source=LeadSource.REFERRAL,
        status=LeadStatus.WON, created_days_ago=75,
        raw="大里三房，1800萬，自住，要有車位，小孩剛上國中",
        fields=dict(location="大里", budget_max=18000000, rooms=3, parking=True,
                    purpose=Purpose.SELF_USE),
        interactions=[
            (InteractionType.VIEWING, "帶看大里兩間", 60),
            (InteractionType.MEETING, "簽約完成", 40),
        ],
        follow_up=None,
    ),
    dict(
        name="潘怡君", phone="0912345018", source=LeadSource.LINE,
        status=LeadStatus.WON, created_days_ago=50,
        raw="投資套房，650萬，逢甲，之前已經買過一間在附近",
        fields=dict(location="逢甲", budget_max=6500000,
                    property_type=PropertyType.STUDIO, purpose=Purpose.INVESTMENT),
        interactions=[
            (InteractionType.LINE, "熟客，直接傳物件", 40),
            (InteractionType.MEETING, "簽約", 28),
        ],
        follow_up=None,
    ),

    # ---------- 流失 ----------
    dict(
        name="徐國強", phone="0912345019", source=LeadSource.WALK_IN,
        status=LeadStatus.LOST, created_days_ago=55,
        raw="原本想買七期，看了幾間之後決定先租一年再說",
        fields=dict(location="七期", urgency=Urgency.LOW),
        interactions=[
            (InteractionType.VIEWING, "帶看七期兩間", 40),
            (InteractionType.CALL, "客戶決定先租不買", 25),
        ],
        follow_up=None,
    ),
    dict(
        name="沈麗華", phone="0912345020", source=LeadSource.PHONE,
        status=LeadStatus.LOST, created_days_ago=45,
        raw="預算談不攏，客戶最後決定再等等看房價",
        fields=dict(location="北區", budget_max=13000000, rooms=3),
        interactions=[
            (InteractionType.CALL, "電訪", 35),
            (InteractionType.VIEWING, "帶看一間，客戶嫌貴", 30),
            (InteractionType.NOTE, "客戶表示先觀望", 22),
        ],
        follow_up=None,
    ),
]
# fmt: on


def _utc(days_ago: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


def build(db, owner: User) -> int:
    today = date.today()

    for spec in LEADS:
        lead = Lead(
            owner_id=owner.id,
            name=spec["name"],
            phone=spec["phone"],
            source=spec["source"],
            status=spec["status"],
            # 原話前面掛標記，--reset 才認得出哪些是這支腳本建的
            raw_requirement=f"{DEMO_TAG} {spec['raw']}",
            **spec["fields"],
        )

        follow_up = spec["follow_up"]
        if follow_up == "muted":
            lead.follow_up_muted = True
        elif isinstance(follow_up, int):
            lead.next_follow_up_at = today + timedelta(days=follow_up)

        # 已約帶看：(幾天後, 幾點)。
        # Demo 一定要有一筆「明天帶看」，否則 Dashboard 上
        # 「明天帶看，今天要確認」那一區永遠是空的 ——
        # 面試官打開看不到這個功能存在。
        viewing = spec.get("viewing")
        if viewing is not None:
            days, hour = viewing
            lead.viewing_scheduled_at = datetime.combine(
                today + timedelta(days=days),
                datetime.min.time().replace(hour=hour),
                tzinfo=timezone.utc,
            )

        # 分數由同一套規則算出來，不是寫死的 ——
        # 否則調整權重之後，Demo 資料會跟系統的實際行為對不上。
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

    db.commit()
    return len(LEADS)


def main() -> int:
    parser = argparse.ArgumentParser(description="建立 Demo 客戶資料")
    parser.add_argument(
        "--reset", action="store_true", help="先刪掉這支腳本建過的資料再重建"
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        owner = db.query(User).filter(User.email == DEMO_EMAIL).one_or_none()
        if owner is None:
            print(f"找不到 {DEMO_EMAIL}，請先註冊這個帳號")
            return 1

        existing = (
            db.query(Lead)
            .filter(Lead.owner_id == owner.id)
            .filter(Lead.raw_requirement.like(f"{DEMO_TAG}%"))
            .all()
        )

        if existing and not args.reset:
            print(f"已經有 {len(existing)} 筆 demo 資料。要重建請加 --reset")
            return 1

        if existing:
            for lead in existing:
                db.delete(lead)
            db.commit()
            print(f"已清除 {len(existing)} 筆舊的 demo 資料")

        count = build(db, owner)

        total = db.query(Lead).filter(Lead.owner_id == owner.id).count()
        print(f"建立了 {count} 位 demo 客戶，這個帳號目前共 {total} 位")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
