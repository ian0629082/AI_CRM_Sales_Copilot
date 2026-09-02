"""看一份情境資料集「考到了哪幾條判準」，不呼叫 OpenAI、不花錢。

用法（在 backend 目錄下）：

    python -m scripts.holdout_coverage              # 看 holdout
    python -m scripts.holdout_coverage --dataset dev
    python -m scripts.holdout_coverage --detail     # 逐筆列出

---

**為什麼需要這支腳本。**

驗證集只有 5 筆的時候，六條判準裡有兩條實際上一次都沒被考到 ——
「時機對得上客戶約的時間」在那 5 筆上全部不適用（沒有客戶講出
「X 再打給我」這種明確回電約定），「帶看確認」只有 1 筆。

一條沒被考過的判準，它的通過率是**憑空的**。那比樣本小更糟糕，
因為它看起來有數字。

所以補題的停止條件不該是「湊滿 15 筆」，而是
**「每條判準至少被考到兩次」** —— 補到那裡，數字才真的在講一件事。

**為什麼這件事不用花錢就能算。**

六條判準裡，有三條的「適不適用」完全由**輸入資料**決定：

| 判準 | 什麼時候不適用 |
|---|---|
| 有用到互動歷史 | 這筆客戶沒有任何互動紀錄 |
| 時機對得上客戶約的時間 | 客戶沒講「X 再打給我」這種明確回電約定 |
| 明天帶看要叫業務去確認 | 明天沒有帶看 |

另外三條（引用有出處、下一步是具體動作、話術裡的數字有出處）
永遠適用，不必檢查。

也就是說，覆蓋率在**還沒呼叫模型之前**就已經定下來了。
這支腳本重用的是評估腳本裡同一套函式，不是另外寫一份判斷 ——
判斷寫兩份，遲早會有一份跟正式評估不一致。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

from app.services import follow_up
from app.services.follow_up_advisor import MAX_INTERACTIONS, build_source_text
from evaluation.followup_criteria import (
    CRITERIA_LABELS,
    Verdict,
    check_timing_matches_appointment,
    check_uses_history,
    check_viewing_confirmed,
)
from scripts.evaluate_followup import build_interactions, build_lead, resolve_today

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
EVALUATION_DIR = BACKEND_DIR / "evaluation"

DATASETS = {
    "holdout": EVALUATION_DIR / "followup_holdout.json",
    "dev": EVALUATION_DIR / "followup_cases.json",
}

# 每條判準至少要被考到這麼多次，數字才算在講一件事。
# 訂 2 而不是 1：只考過一次的話，那條判準的通過率不是 0% 就是 100%，
# 對「這個功能行不行」幾乎沒有提供任何資訊。
MIN_APPLICABLE = 2

# 這三條的適用性由模型的輸出決定，事先算不出來 —— 但它們永遠適用。
ALWAYS_APPLICABLE = ("grounding", "actionable", "numbers_grounded")

# 判準沒被考到時，該去補哪一種客戶。
# 寫成給業務看的話，而不是「請增加 timing_matches 的樣本」——
# 出題的人是照著手上真實的客戶在想，不是照著判準的名字在想。
WHAT_TO_ADD = {
    "uses_history": "跟過一陣子、底下有互動紀錄的客戶（不是剛建檔就沒下文的）",
    # 提示照業務實際會打的字寫。第一版寫成「你下週三再打給我」——
    # 那是客戶的口吻，而互動紀錄是業務事後轉述，根本不會出現那種句子。
    "timing_matches": (
        "約好了下次聯絡時間的客戶。互動紀錄照你平常打的寫就好，例如"
        "「客戶請我下週三聯繫」「約下週三回電」「客戶說週五前給我答覆」"
    ),
    "viewing_confirmed": "隔天就要帶看的客戶（已約帶看那一欄填明天）",
}


def applicability(case: dict, today) -> dict[str, bool]:
    """這一筆會考到哪幾條判準。

    完全走正式評估的那條路：同樣用 build_lead / build_interactions 把 JSON
    還原成 model 物件，再用 Rule Engine 判斷帶看，
    這樣算出來的覆蓋率跟實際跑評估時看到的才會一致。
    """
    lead = build_lead(case, today)
    interactions = build_interactions(case, today)
    status = follow_up.evaluate(lead, interactions, today)

    recent = interactions[:MAX_INTERACTIONS]
    source_text = build_source_text(lead, recent)
    interaction_text = "\n".join(i.content for i in recent)

    # 約定只看最新一筆互動，跟正式評估用同一條規則
    # （整包歷史丟進去的話，早就被取代的舊約定會被當成還有效）。
    # 沒有互動紀錄時退回客戶原話。
    latest_interaction = recent[0].content if recent else source_text
    recorded_days_ago = (today - recent[0].created_at.date()).days if recent else None

    # 直接呼叫真正的判準函式，看它回不回 N/A。
    # 傳空字串當作模型的輸出：這幾條的 N/A 判斷只看輸入，
    # 給什麼建議都不影響「適不適用」，只影響「過不過」。
    checks = {
        "uses_history": check_uses_history([], interaction_text),
        "timing_matches": check_timing_matches_appointment(
            "", latest_interaction, today, recorded_days_ago
        ),
        "viewing_confirmed": check_viewing_confirmed(
            "", "", status.bucket is follow_up.FollowUpBucket.VIEWING_CONFIRM
        ),
    }
    result = {name: r.verdict is not Verdict.NOT_APPLICABLE for name, r in checks.items()}
    result.update({name: True for name in ALWAYS_APPLICABLE})
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=sorted(DATASETS), default="holdout")
    parser.add_argument(
        "--detail", action="store_true", help="逐筆列出每條判準考不考得到"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    path = DATASETS[args.dataset]

    if not path.exists():
        print(f"找不到 {path.name}。holdout 要先執行 python -m scripts.build_holdout")
        return 1

    dataset = json.loads(path.read_text(encoding="utf-8"))
    cases = dataset["cases"]
    today = resolve_today(dataset)

    coverage = {case["id"]: applicability(case, today) for case in cases}
    total = len(cases)

    print(f"\n資料集：{path.name}（{total} 筆，基準日 {today}）\n")
    print(f"{'判準':<22}{'考到幾筆':>10}")
    print("-" * 34)

    gaps: list[str] = []
    for name in CRITERIA_LABELS:
        hits = sum(1 for c in coverage.values() if c[name])
        # 這裡刻意只用中文與 ASCII：Windows 的終端機預設是 cp950，
        # 印 ✓ 或 ← 會直接丟 UnicodeEncodeError，把整支腳本打斷。
        mark = "  夠" if hits >= MIN_APPLICABLE else "  不夠"
        if hits < MIN_APPLICABLE:
            gaps.append(name)
        print(f"{CRITERIA_LABELS[name]:<22}{hits:>6} / {total}{mark}")

    if args.detail:
        print("\n逐筆：")
        for case_id, flags in coverage.items():
            considered = [CRITERIA_LABELS[n] for n, ok in flags.items() if ok]
            print(f"  {case_id}: {'、'.join(considered)}")

    if gaps:
        print(f"\n還缺這幾種情境（每條判準至少要 {MIN_APPLICABLE} 筆才算考過）：")
        for name in gaps:
            hint = WHAT_TO_ADD.get(name)
            if hint:
                print(f"  - {CRITERIA_LABELS[name]}：補「{hint}」")
            else:
                print(f"  - {CRITERIA_LABELS[name]}")
        print("\n但照真實比例填，不要為了補洞硬掰情境 ——")
        print("硬掰出來的情境正是這份資料集最不能有的東西。")
    else:
        print(f"\n六條判準都至少被考到 {MIN_APPLICABLE} 筆，覆蓋沒有缺口。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
