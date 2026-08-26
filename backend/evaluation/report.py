"""把評估結果渲染成 Markdown 報告。

輸出成檔案而不是只印在終端機，是因為這份報告要能：

1. 進 git，讓「換了 prompt 之後有沒有比較準」有紀錄可比
2. 貼進履歷或面試 —— 「Location 98%」這種數字要有出處
"""

from __future__ import annotations

from datetime import datetime

from evaluation.metrics import FIELDS, Outcome, Report

FIELD_LABEL = {
    "location": "區域 location",
    "budget_min": "預算下限 budget_min",
    "budget_max": "預算上限 budget_max",
    "budget_is_approximate": "預算是否概數",
    "rooms": "房數 rooms",
    "property_type": "房屋類型",
    "building_age_max": "屋齡上限",
    "parking": "車位 parking",
    "purpose": "購屋目的",
    "purchase_timeline": "購屋時程",
}

OUTCOME_LABEL = {
    Outcome.MISS: "漏抽",
    Outcome.HALLUCINATION: "捏造",
    Outcome.WRONG: "抽錯",
}


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _fmt(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


DATASET_CAVEAT = {
    "dev": (
        "⚠️ 這是**開發集**。Prompt 的規則是看著它的錯誤補出來的，"
        "分數必然偏高，不適合對外引用。要引用請用 holdout 那份報告。"
    ),
    "holdout": (
        "✅ 這是**驗證集**，從未被用來修改 prompt。"
        "模型是在完全沒看過這些句子的情況下作答的，這裡的數字才可以對外引用。"
    ),
    "final": (
        "🔒 這是**期末考資料集**：由具房仲業務實務經驗、且未讀過 prompt 的人出題，"
        "句子取材自真實業務場景。這份的數字是所有報告裡最接近真實表現的。"
        "**不得因為這份的結果去修改 prompt。**"
    ),
}


def render_markdown(report: Report, *, dataset_name: str, dataset_version: str) -> str:
    lines: list[str] = []
    add = lines.append

    add(f"# AI 需求解析評估報告：{report.model}")
    add("")
    add(f"> 產生時間：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    add(f"> 模型：`{report.model}`　Prompt 版本：`{report.prompt_version}`")
    add(
        f"> 資料集：`{dataset_name}` {dataset_version}，共 {len(report.cases)} 筆"
    )
    add("")
    # 每份報告都自己帶著這句警告。
    # 報告會被單獨貼給別人看，缺了這句，開發集的分數就會被當成真實表現。
    add(f"> {DATASET_CAVEAT[dataset_name]}")
    add("")

    # --- 總覽 ---
    add("## 一、總覽")
    add("")
    add("| 指標 | 數字 | 這個數字在說什麼 |")
    add("|---|---|---|")
    add(
        f"| 欄位正確率 | **{_pct(report.field_accuracy)}** "
        f"| {len(report.cases)} 筆 × 10 個欄位攤平之後的整體正確率 |"
    )
    add(
        f"| 完全正確率 | **{_pct(report.exact_match_rate)}** "
        "| 10 個欄位全對的案例比例，最嚴格也最貼近使用者感受 |"
    )
    add(
        f"| 捏造率 | **{_pct(report.hallucination_rate)}** "
        "| 客戶沒提到的欄位裡，模型憑空生出資訊的比例（越低越好） |"
    )
    add("")

    if report.failed_cases:
        add(
            f"> ⚠️ 有 {len(report.failed_cases)} 筆在呼叫或驗證階段就失敗，"
            "未列入上面的統計。詳見第四節。"
        )
        add("")

    # --- 逐欄位 ---
    add("## 二、逐欄位準確率")
    add("")
    add("欄位正確率會被 null 灌水（資料集裡本來就有大量欄位的正確答案是 null，")
    add("一個永遠回 null 的模型光靠猜空值就有不錯的分數），所以另外拆出三種錯誤來看。")
    add("")
    add("| 欄位 | 正確率 | Recall | Precision | 漏抽 | 捏造 | 抽錯 |")
    add("|---|---|---|---|---|---|---|")
    for name in FIELDS:
        stats = report.per_field[name]
        add(
            f"| {FIELD_LABEL[name]} | {_pct(stats.accuracy)} | {_pct(stats.recall)} "
            f"| {_pct(stats.precision)} | {stats.miss} | {stats.hallucination} "
            f"| {stats.wrong} |"
        )
    add("")
    add("- **Recall**：客戶真的有講的那些欄位裡，抽對了幾成 —— 低代表容易漏資訊")
    add("- **Precision**：模型填了值的那些欄位裡，有幾成是對的 —— 低代表填進 CRM 的資料不可信")
    add("")

    # --- Error Analysis ---
    add("## 三、Error Analysis")
    add("")

    wrong_cases = [c for c in report.cases if not c.is_exact_match]
    if not wrong_cases:
        add("這一輪沒有任何錯誤。")
    else:
        add(f"共 {len(wrong_cases)} 筆案例至少有一個欄位不符預期。")
        add("")
        for case in wrong_cases:
            add(f"### {case.case_id}")
            add("")
            add(f"> {case.raw_requirement}")
            add("")
            if case.tags:
                add(f"標籤：{'、'.join(f'`{t}`' for t in case.tags)}")
                add("")
            add("| 欄位 | 應為 | 模型給的 | 類型 |")
            add("|---|---|---|---|")
            for name, outcome in case.errors().items():
                add(
                    f"| {FIELD_LABEL[name]} | `{_fmt(case.expected.get(name))}` "
                    f"| `{_fmt(case.actual.get(name))}` | {OUTCOME_LABEL[outcome]} |"
                )
            add("")

    # --- 失敗案例 ---
    if report.failed_cases:
        add("## 四、呼叫或驗證失敗")
        add("")
        add("這些案例連結構化輸出都沒拿到，通常是逾時或數值超出 Pydantic 的合理範圍。")
        add("")
        add("| 案例 | 原因 |")
        add("|---|---|")
        for case_id, reason in report.failed_cases:
            add(f"| {case_id} | {reason} |")
        add("")

    # --- 成本 ---
    add("## 五、成本與延遲")
    add("")
    total_tokens = report.prompt_tokens + report.completion_tokens
    add("| 項目 | 數字 |")
    add("|---|---|")
    add(f"| Prompt tokens | {report.prompt_tokens:,} |")
    add(f"| Completion tokens | {report.completion_tokens:,} |")
    add(f"| 合計 | {total_tokens:,} |")
    if report.cases:
        add(f"| 每筆平均 tokens | {total_tokens / len(report.cases):,.0f} |")
    add(f"| 延遲中位數 | {report.median_latency_ms or '—'} ms |")
    add("")
    add("> 換算成金額請對照 OpenAI 當期定價；這裡只記 token 數，")
    add("> 因為定價會變，而 token 數是這次執行的事實。")
    add("")

    return "\n".join(lines)
