"""把所有客戶的分數重算一次。

什麼時候要跑：

- Sprint 5 之前建立的客戶，lead_score 是 NULL —— 他們從來沒被計分過
- 調整了計分權重之後，舊資料還停在舊分數

用法（在 backend 目錄下）：
    python -m scripts.rescore_leads

安全：計分是確定性的規則，同一筆資料重算幾次結果都一樣，
重複執行不會有副作用。
"""

from app.db.database import SessionLocal
from app.models.lead import Lead
from app.services.scoring_service import calculate_score


def main() -> None:
    db = SessionLocal()
    try:
        leads = db.query(Lead).all()
        changed = 0

        for lead in leads:
            result = calculate_score(lead)
            if lead.lead_score != result.score or lead.lead_level != result.level:
                lead.lead_score = result.score
                lead.lead_level = result.level
                changed += 1

        db.commit()
        print(f"共 {len(leads)} 位客戶，更新了 {changed} 筆分數")
    finally:
        db.close()


if __name__ == "__main__":
    main()
