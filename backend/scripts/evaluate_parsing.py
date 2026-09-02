"""跑一次 AI 需求解析的評估，輸出 Markdown 報告。

用法（在 backend 目錄下）：

    # 用 .env 裡設定的模型跑整份資料集
    python -m scripts.evaluate_parsing

    # 換一個模型跑，用來比較準確率與成本
    python -m scripts.evaluate_parsing --model gpt-5.4

    # 用舊版 prompt 跑，跟新版比較
    python -m scripts.evaluate_parsing --prompt-version lead_analysis_v1

    # 只跑前 5 筆，先確認流程是通的（會真的花錢，先小量試）
    python -m scripts.evaluate_parsing --limit 5

報告輸出到 docs/evaluation/<模型>__<prompt 版本>.md，
原始結果同時存成 .json 供後續分析。

**這支腳本會呼叫真實的 OpenAI，會花錢。**
單元測試不會碰它 —— 測試用的是假 provider，跑的是 tests/ 底下那些。
兩者分工：測試確保「程式沒壞」，這支腳本回答「模型準不準」。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from concurrent.futures import ThreadPoolExecutor

from app.core.config import settings
from app.core.exceptions import AIServiceError
from app.services.ai_service import DEFAULT_PROMPT_VERSION, PROMPTS, AIService
from app.services.llm_provider import OpenAIProvider
from evaluation.console import force_utf8_output
from evaluation.metrics import CaseResult, build_report, compare_case
from evaluation.report import render_markdown

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
EVALUATION_DIR = BACKEND_DIR / "evaluation"
OUTPUT_DIR = BACKEND_DIR.parent / "docs" / "evaluation"

# dev  = 開發集，Error Analysis 與調 prompt 都看這一份
# hold = 驗證集，從沒被用來調 prompt，要引用數字時引用這一份
DATASETS = {
    "dev": EVALUATION_DIR / "dataset.json",
    "holdout": EVALUATION_DIR / "holdout.json",
    "final": EVALUATION_DIR / "final_test.json",
}

# final 是期末考：由具業務實務經驗、且未讀過 prompt 的人出題，
# 鎖到 Sprint 7 上線前才第一次執行。
#
# 用程式擋而不是靠記性 —— 半年後誰還記得哪一份不能隨便跑？
# 想跑要多打一個很長的旗標，那個動作本身就是在提醒你正在做什麼。
LOCKED_DATASETS = {"final"}
UNLOCK_FLAG = "--yes-i-am-spending-the-final-test"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="評估 AI 需求解析的準確率")
    parser.add_argument(
        "--model",
        default=settings.OPENAI_MODEL,
        help="要評估的模型，預設讀 .env 的 OPENAI_MODEL",
    )
    parser.add_argument(
        "--prompt-version",
        default=DEFAULT_PROMPT_VERSION,
        choices=sorted(PROMPTS),
        # 舊版 prompt 留著不刪，就是為了能用同一份資料集重跑，
        # 讓「v2 有沒有比 v1 準」是量出來的而不是感覺出來的。
        help="要評估的 prompt 版本",
    )
    parser.add_argument(
        "--dataset",
        default="dev",
        choices=sorted(DATASETS),
        help=(
            "dev 開發集（可以拿來調 prompt）、"
            "holdout 驗證集（只量測）、"
            "final 期末考（鎖定，Sprint 7 才開）"
        ),
    )
    parser.add_argument(
        UNLOCK_FLAG,
        action="store_true",
        dest="unlock_final",
        help="確認要動用期末考資料集。跑完之後它就不再是乾淨的了。",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="只跑前 N 筆（先小量確認流程）"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        # 平行送出可以把 40 筆從約兩分鐘壓到半分鐘。
        # 不開太大是因為 OpenAI 有 rate limit，撞到之後重試反而更慢。
        help="同時送出的請求數，預設 4",
    )
    return parser.parse_args()


def run_case(service: AIService, case: dict) -> tuple[CaseResult | None, tuple[str, str] | None, dict]:
    """跑一筆案例。回傳 (結果, 失敗原因, 用量)。

    失敗的案例不能直接當成「全錯」丟進統計 —— 逾時是基礎設施問題，
    跟模型理解錯誤是兩回事，混在一起算會讓準確率變得無法解讀。
    所以它們被單獨列出來。
    """
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": None}

    try:
        outcome = service.parse_requirement(case["raw_requirement"])
    except AIServiceError as exc:
        return None, (case["id"], str(exc.message)), usage

    actual = outcome.requirement.model_dump(mode="json")
    usage = {
        "prompt_tokens": outcome.prompt_tokens or 0,
        "completion_tokens": outcome.completion_tokens or 0,
        "latency_ms": outcome.latency_ms,
    }

    result = CaseResult(
        case_id=case["id"],
        raw_requirement=case["raw_requirement"],
        tags=case.get("tags", []),
        expected=case["expected"],
        actual=actual,
        outcomes=compare_case(case["expected"], actual),
    )
    return result, None, usage


def main() -> int:
    force_utf8_output()
    args = parse_args()

    if not settings.OPENAI_API_KEY:
        print("錯誤：未設定 OPENAI_API_KEY，無法執行評估", file=sys.stderr)
        return 1

    if args.dataset in LOCKED_DATASETS and not args.unlock_final:
        print(
            f"「{args.dataset}」是鎖定的期末考資料集，不能隨手跑。\n"
            "\n"
            "它的價值全部來自「從沒被拿來調整過任何東西」。\n"
            "跑過一次、又據此改了 prompt，它就變成第三個練習題。\n"
            "\n"
            f"確定要用掉它，加上 {UNLOCK_FLAG}",
            file=sys.stderr,
        )
        return 1

    dataset = json.loads(DATASETS[args.dataset].read_text(encoding="utf-8"))
    cases = dataset["cases"][: args.limit] if args.limit else dataset["cases"]

    print(
        f"模型 {args.model}　Prompt {args.prompt_version}　"
        f"資料集 {args.dataset}　案例 {len(cases)} 筆"
    )
    print(f"平行度 {args.workers}，開始執行⋯⋯（會呼叫真實 OpenAI）")

    service = AIService(
        OpenAIProvider(
            api_key=settings.OPENAI_API_KEY,
            model=args.model,
            timeout=settings.OPENAI_TIMEOUT_SECONDS,
        ),
        prompt_version=args.prompt_version,
    )

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        outputs = list(pool.map(lambda c: run_case(service, c), cases))

    results = [r for r, _, _ in outputs if r is not None]
    failures = [f for _, f, _ in outputs if f is not None]
    usages = [u for _, _, u in outputs]

    report = build_report(
        model=args.model,
        prompt_version=args.prompt_version,
        cases=results,
        failed_cases=failures,
        prompt_tokens=sum(u["prompt_tokens"] for u in usages),
        completion_tokens=sum(u["completion_tokens"] for u in usages),
        latencies_ms=[u["latency_ms"] for u in usages if u["latency_ms"] is not None],
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # 檔名帶模型與 prompt 版本，不同組合的報告才不會互相覆蓋
    stem = f"{args.model}__{args.prompt_version}__{args.dataset}".replace("/", "_")

    markdown = render_markdown(
        report,
        dataset_name=args.dataset,
        dataset_version=dataset["meta"]["version"],
    )
    (OUTPUT_DIR / f"{stem}.md").write_text(markdown, encoding="utf-8")

    # 原始結果另存 JSON：報告是給人看的，這份是給後續分析用的
    (OUTPUT_DIR / f"{stem}.json").write_text(
        json.dumps(
            {
                "model": args.model,
                "prompt_version": args.prompt_version,
                "dataset": args.dataset,
                "dataset_version": dataset["meta"]["version"],
                "cases": [
                    {
                        "case_id": c.case_id,
                        "raw_requirement": c.raw_requirement,
                        "tags": c.tags,
                        "expected": c.expected,
                        "actual": c.actual,
                        "outcomes": {f: o.value for f, o in c.outcomes.items()},
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

    def pct(v: float | None) -> str:
        return "—" if v is None else f"{v * 100:.1f}%"

    print()
    print(f"  欄位正確率   {pct(report.field_accuracy)}")
    print(f"  完全正確率   {pct(report.exact_match_rate)}")
    print(f"  捏造率       {pct(report.hallucination_rate)}")
    if failures:
        print(f"  失敗         {len(failures)} 筆")
    print()
    print(f"報告已寫入 {OUTPUT_DIR / f'{stem}.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
