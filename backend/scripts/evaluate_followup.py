"""跑一次 AI 跟進建議的評估，輸出 Markdown 報告。

用法（在 backend 目錄下）：

    # 用 .env 裡設定的模型跑整份情境資料集（只跑程式可驗的第一層判準）
    python -m scripts.evaluate_followup

    # 加跑 LLM Judge（第二層），會多花一次 API 費用
    python -m scripts.evaluate_followup --judge

    # 先跑 2 筆確認流程是通的
    python -m scripts.evaluate_followup --limit 2

    # 換模型比較
    python -m scripts.evaluate_followup --model gpt-5.4

報告輸出到 docs/evaluation/followup__<模型>__<prompt 版本>.md。

**這支腳本會呼叫真實的 OpenAI，會花錢。**

---

跟 evaluate_parsing.py 最大的差別：**這份資料集沒有 expected 欄位**。

需求解析可以逐欄位跟人工標註比對，跟進建議不行 ——
同一位客戶，「先打電話問他考慮得如何」跟「先把物件資料傳過去」都合理。
所以這裡評的是判準（見 evaluation/followup_criteria.py），不是答案。

另一個關鍵差別：這裡拿去評估的是**模型的原始輸出**。
正式流程會把找不到出處的引用先拿掉再顯示給業務，
若拿處理過的結果來評估，會量到 0% 捏造然後開心地收工。
FollowUpOutcome.ungrounded_evidence 留著就是為了這一刻。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

from app.core.config import settings
from app.core.exceptions import AIServiceError
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
from app.services import follow_up
from app.services.follow_up_advisor import (
    DEFAULT_FOLLOW_UP_PROMPT_VERSION,
    FOLLOW_UP_PROMPTS,
    MAX_INTERACTIONS,
    FollowUpAdvisor,
    build_source_text,
)
from app.services.llm_provider import LLMError, OpenAIProvider
from app.services.scoring_service import calculate_score
from evaluation.followup_criteria import FollowUpReport, evaluate_case
from evaluation.followup_report import render_followup_markdown

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
CASES_PATH = BACKEND_DIR / "evaluation" / "followup_cases.json"
OUTPUT_DIR = BACKEND_DIR.parent / "docs" / "evaluation"

# 評估時固定用這一天當「今天」。
#
# 不用 date.today() 是為了讓結果可重現：資料集裡寫的是「幾天前」，
# 真的用今天去算的話，同一份資料集在不同日子跑會餵給模型不同的日期，
# 兩份報告就不能直接比較了。
EVAL_TODAY = date(2026, 1, 15)


# ----------------------------------------------------------------------
# 把 JSON 情境變成 model 物件
# ----------------------------------------------------------------------


def build_lead(case: dict) -> Lead:
    """組出一個沒有進資料庫的 Lead。

    SQLAlchemy 的 Column default 只在 INSERT 時才套用，
    這種 transient 物件拿不到預設值 —— 所以每個會被 Scoring 或
    Follow-up 讀到的欄位都要明確給值，不能靠 model 上寫的 default。
    漏掉一個的症狀是分數莫名其妙少幾分，而且很難查。
    """
    data = case["lead"]
    created = EVAL_TODAY - timedelta(days=case.get("days_since_created", 1))

    next_follow_up = None
    if "next_follow_up_in_days" in case:
        next_follow_up = EVAL_TODAY + timedelta(days=case["next_follow_up_in_days"])

    lead = Lead(
        id=0,
        name=data["name"],
        phone=data.get("phone"),
        email=data.get("email"),
        source=LeadSource.WEB_FORM,
        status=LeadStatus(data.get("status", "NEW")),
        raw_requirement=data.get("raw_requirement"),
        location=data.get("location"),
        budget_min=data.get("budget_min"),
        budget_max=data.get("budget_max"),
        budget_is_approximate=data.get("budget_is_approximate", False),
        rooms=data.get("rooms"),
        property_type=PropertyType(data["property_type"]) if data.get("property_type") else None,
        building_age_max=data.get("building_age_max"),
        parking=data.get("parking"),
        purpose=Purpose(data["purpose"]) if data.get("purpose") else None,
        purchase_timeline=data.get("purchase_timeline"),
        urgency=Urgency(data["urgency"]) if data.get("urgency") else None,
        next_follow_up_at=next_follow_up,
        follow_up_muted=False,
    )
    lead.created_at = datetime.combine(created, datetime.min.time())
    return lead


def build_interactions(case: dict) -> list[Interaction]:
    """互動紀錄由新到舊，跟正式流程從資料庫撈出來的順序一致。

    順序不能弄反：advisor 只取前 MAX_INTERACTIONS 筆，
    反了的話評估餵的是最舊的幾筆，量到的就不是正式流程的表現。
    """
    items = []
    for index, raw in enumerate(case.get("interactions", [])):
        item = Interaction(
            id=index,
            lead_id=0,
            type=InteractionType(raw["type"]),
            content=raw["content"],
        )
        item.created_at = datetime.combine(
            EVAL_TODAY - timedelta(days=raw["days_ago"]), datetime.min.time()
        )
        items.append(item)
    return sorted(items, key=lambda i: i.created_at, reverse=True)


# ----------------------------------------------------------------------
# LLM Judge（第二層）
# ----------------------------------------------------------------------

JUDGE_PROMPT = """你是台灣房仲公司的業務主管，正在檢查一則要交給業務使用的跟進建議。

你會拿到「客戶說過的話」與「一則建議」。請判斷三件事，每一件回 true 或 false：

1. tone_natural：話術像不像真人業務講的話。
   書面語、生硬的客套（「敝公司」「謹此」）、太像行銷簡訊 → false

2. action_specific：下一步動作是不是一個做得到的具體動作。
   「持續追蹤」「保持聯繫」「加強互動」這種 → false

3. no_fabrication：建議裡提到的每一件關於客戶的事，
   是不是都能在「客戶說過的話」裡找到。
   出現客戶沒說過的物件、路名、價格、職業、家庭狀況 → false
   （建議業務「去問客戶某件事」不算捏造，那是在承認資訊不足）
   （用「客戶姓名」那一欄給的稱呼叫他，也**不算**捏造 ——
     那是 CRM 裡本來就有的資料，只是客戶不會在講需求時報自己的名字）

comment 用一句話說明你最在意的問題，沒問題就寫「無」。

只依據給你的資料判斷，不要腦補客戶可能還說過什麼。"""

JUDGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "tone_natural": {"type": "boolean"},
        "action_specific": {"type": "boolean"},
        "no_fabrication": {"type": "boolean"},
        "comment": {"type": "string"},
    },
    "required": ["tone_natural", "action_specific", "no_fabrication", "comment"],
}


def judge_case(
    provider: OpenAIProvider, suggestion: dict, source_text: str, lead_name: str
) -> dict | None:
    """讓另一次模型呼叫來評這則建議。

    Judge 只拿到「客戶姓名」「客戶說過的話」與「建議」，
    **拿不到分數、狀態、逾期天數** ——
    給越多背景，它越容易被那些數字說服而放過內容本身。

    姓名一定要給。第一輪評估沒給，判官就把「李先生您好」判成捏造，
    理由是「客戶原話裡沒有名字」—— 它說得沒錯，但客戶本來就不會在
    講需求時報自己的名字，那是 CRM 欄位裡的資料。
    判官只能依據你給它的東西判斷，少給一樣，它就會穩定地誤判一整類案例。

    刻意用另一個 prompt 而不是叫同一個 service 再跑一次：
    判官跟被評估的對象要是兩個角色，否則它只是在確認自己剛剛寫的東西。
    這仍然無法完全避免「同一類模型的共同盲點」，
    所以 Judge 的數字只能看趨勢，要引用得先用人工抽樣校準過。
    """
    user_prompt = (
        f"【客戶姓名】\n{lead_name}\n\n"
        f"【客戶說過的話】\n{source_text}\n\n"
        f"【建議】\n"
        f"下一步：{suggestion.get('next_action', '')}\n"
        f"時機：{suggestion.get('suggested_timing', '')}\n"
        f"話術：{suggestion.get('talking_point', '')}"
    )

    try:
        response = provider.complete_json(
            system_prompt=JUDGE_PROMPT,
            user_prompt=user_prompt,
            schema_name="follow_up_judgement",
            json_schema=JUDGE_SCHEMA,
        )
        return json.loads(response.content)
    except (LLMError, json.JSONDecodeError) as exc:
        # Judge 失敗不能讓整輪評估掛掉 —— 第一層的數字仍然有效
        print(f"  （Judge 失敗：{exc}）", file=sys.stderr)
        return None


# ----------------------------------------------------------------------


def run_case(advisor: FollowUpAdvisor, judge_provider, case: dict):
    """跑一筆情境。回傳 (結果, 失敗原因, 用量)。"""
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": None}
    lead = build_lead(case)
    interactions = build_interactions(case)

    score = calculate_score(lead)
    status = follow_up.evaluate(lead, interactions, EVAL_TODAY)

    try:
        outcome = advisor.suggest(lead, interactions, score, status, EVAL_TODAY)
    except AIServiceError as exc:
        return None, (case["id"], str(exc.message)), usage

    usage = {
        "prompt_tokens": outcome.prompt_tokens or 0,
        "completion_tokens": outcome.completion_tokens or 0,
        "latency_ms": outcome.latency_ms,
    }

    # 評估要看模型**原始**的輸出。
    # advisor 已經把找不到出處的引用拿掉了，這裡要把它們加回來，
    # 否則 grounding 這條判準永遠 100% 通過，等於沒有在評估。
    raw = outcome.suggestion.model_dump(mode="json")
    raw["evidence"] = [*raw["evidence"], *outcome.ungrounded_evidence]

    recent = interactions[:MAX_INTERACTIONS]
    result = evaluate_case(
        case_id=case["id"],
        tags=case.get("tags", []),
        suggestion=raw,
        source_text=build_source_text(lead, recent),
        interaction_text="\n".join(i.content for i in recent),
    )

    if judge_provider is not None:
        result.judge = judge_case(
            judge_provider, raw, build_source_text(lead, recent), lead.name
        )

    return result, None, usage


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="評估 AI 跟進建議的品質")
    parser.add_argument("--model", default=settings.OPENAI_MODEL)
    parser.add_argument(
        "--prompt-version",
        default=DEFAULT_FOLLOW_UP_PROMPT_VERSION,
        choices=sorted(FOLLOW_UP_PROMPTS),
    )
    parser.add_argument(
        "--judge",
        action="store_true",
        help="加跑 LLM Judge（第二層）。每筆會多一次 API 呼叫。",
    )
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 筆")
    parser.add_argument("--workers", type=int, default=4)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not settings.OPENAI_API_KEY:
        print("錯誤：未設定 OPENAI_API_KEY，無法執行評估", file=sys.stderr)
        return 1

    dataset = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    cases = dataset["cases"][: args.limit] if args.limit else dataset["cases"]

    print(
        f"模型 {args.model}　Prompt {args.prompt_version}　情境 {len(cases)} 筆"
        f"{'　（含 LLM Judge）' if args.judge else ''}"
    )
    print(f"平行度 {args.workers}，開始執行⋯⋯（會呼叫真實 OpenAI）")

    provider = OpenAIProvider(
        api_key=settings.OPENAI_API_KEY,
        model=args.model,
        timeout=settings.OPENAI_TIMEOUT_SECONDS,
    )
    advisor = FollowUpAdvisor(provider, prompt_version=args.prompt_version)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        outputs = list(
            pool.map(lambda c: run_case(advisor, provider if args.judge else None, c), cases)
        )

    results = [r for r, _, _ in outputs if r is not None]
    failures = [f for _, f, _ in outputs if f is not None]
    usages = [u for _, _, u in outputs]

    report = FollowUpReport(
        model=args.model,
        prompt_version=args.prompt_version,
        cases=results,
        failed_cases=failures,
        prompt_tokens=sum(u["prompt_tokens"] for u in usages),
        completion_tokens=sum(u["completion_tokens"] for u in usages),
        latencies_ms=[u["latency_ms"] for u in usages if u["latency_ms"] is not None],
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"followup__{args.model}__{args.prompt_version}".replace("/", "_")

    (OUTPUT_DIR / f"{stem}.md").write_text(
        render_followup_markdown(
            report, dataset_version=dataset["meta"]["version"], judged=args.judge
        ),
        encoding="utf-8",
    )

    # 原始結果另存 JSON。
    # 改了判準之後可以直接拿這份重跑統計，不必再花一次錢打模型。
    (OUTPUT_DIR / f"{stem}.json").write_text(
        json.dumps(
            {
                "model": args.model,
                "prompt_version": args.prompt_version,
                "dataset_version": dataset["meta"]["version"],
                "cases": [
                    {
                        "case_id": c.case_id,
                        "tags": c.tags,
                        "suggestion": c.suggestion,
                        "source_text": c.source_text,
                        "criteria": [
                            {"name": r.name, "verdict": r.verdict.value, "detail": r.detail}
                            for r in c.criteria
                        ],
                        "judge": c.judge,
                    }
                    for c in report.cases
                ],
                "failures": [{"case_id": i, "reason": r} for i, r in failures],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    stats = report.per_criterion
    print()
    print(f"  四條全過      {(report.clean_rate or 0) * 100:.1f}%")
    for name, s in stats.items():
        rate = "—" if s.pass_rate is None else f"{s.pass_rate * 100:.1f}%"
        print(f"  {name:<18}{rate}")
    if failures:
        print(f"  執行失敗      {len(failures)} 筆")
    print()
    print(f"報告已寫入 {OUTPUT_DIR / f'{stem}.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
