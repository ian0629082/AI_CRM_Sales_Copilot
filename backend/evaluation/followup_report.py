"""把跟進建議的評估結果渲染成 Markdown 報告。

跟需求解析的報告（report.py）長得不一樣，因為要回答的問題不同：
那份問「準確率多少」，這份問「有沒有踩到紅線，以及踩在哪裡」。

所以這份報告的重點不是一個漂亮的數字，而是**失敗案例的清單**。
Criteria-based 評估的價值在於它指得出「這一則建議在哪一句話上出了問題」，
一個 92% 的總分講不出這件事。
"""

from __future__ import annotations

from datetime import datetime

from evaluation.followup_criteria import (
    CRITERIA_LABELS,
    CRITERIA_ORDER,
    FollowUpReport,
)


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


DATASET_CAVEAT = {
    "dev": (
        "⚠️ 這是**開發集**。Prompt 的規則是看著它的失敗案例補出來的，"
        "分數必然偏高，**不適合對外引用**。要引用請用 holdout 那份報告。"
    ),
    "holdout": (
        "✅ 這是**驗證集**，從未被用來修改 prompt，"
        "而且是由具房仲實務經驗、未讀過 prompt 的人出題的。"
        "模型在完全沒看過這些情境的狀況下作答，這裡的數字才可以對外引用。"
    ),
}


def render_followup_markdown(
    report: FollowUpReport, *, dataset_version: str, judged: bool, dataset_name: str = "dev"
) -> str:
    lines: list[str] = []
    add = lines.append

    add(f"# AI 跟進建議評估報告：{report.model}")
    add("")
    add(f"- 產生時間：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    add(f"- Prompt 版本：`{report.prompt_version}`")
    total = len(report.cases) + len(report.failed_cases)
    add(
        f"- 情境資料集：{dataset_name} {dataset_version}，{total} 筆"
        + (f"（{len(report.failed_cases)} 筆執行失敗，未計入統計）" if report.failed_cases else "")
    )
    add("")
    add(DATASET_CAVEAT.get(dataset_name, ""))
    add("")

    add("> 這份評估**沒有標準答案可以比對**。")
    add("> 需求解析可以逐欄位算準確率，跟進建議不行 ——")
    add("> 同一位客戶有十種合理的跟法，模型選了其中一種不代表它錯。")
    add(">")
    add("> 所以這裡改成問一組判準：不問「答案對不對」，")
    add("> 問「有沒有踩到紅線、有沒有做到該做的事」。")
    add("")

    # --- 頭條數字 ---
    add("## 一句話結論")
    add("")
    add(f"**{_pct(report.clean_rate)}** 的建議四條判準全過，可以直接交到業務手上。")
    add("")
    add("逐條通過率會出現「每條都 90%，但沒有一則是四條全過」的情況 ——")
    add("而業務拿到的是一整則建議，不是四條分開的指標。")
    add("")

    # --- 逐條判準 ---
    add("## 判準通過率")
    add("")
    add("| 判準 | 通過 | 失敗 | 不適用 | 通過率 |")
    add("|---|---:|---:|---:|---:|")

    stats = report.per_criterion
    for name in CRITERIA_ORDER:
        s = stats[name]
        add(
            f"| {CRITERIA_LABELS[name]} | {s.passed} | {s.failed} | "
            f"{s.not_applicable} | {_pct(s.pass_rate)} |"
        )
    add("")
    add("通過率的分母不含「不適用」。把不適用算成通過的話，")
    add("「有用到互動歷史」這條在一份全是新客戶的資料集上會顯示 100%，")
    add("而它實際上一次都沒被考過。")
    add("")

    add("其中**引用有出處**是最不能妥協的一條。")
    add("CRM 裡出現客戶從沒說過的資訊，比話術寫得平淡嚴重得多 ——")
    add("業務照著一句捏造的話打過去，客戶當場就知道他沒在聽。")
    add("")

    # --- 失敗清單 ---
    failures = [c for c in report.cases if c.failures]
    add("## 失敗案例")
    add("")
    if not failures:
        add("這一輪沒有任何案例踩到判準。")
        add("")
        add("要注意這**不等於**建議寫得好 —— 第一層判準守的是紅線（沒有捏造、")
        add("不是空話），守住紅線只代表「可以拿給人看」，不代表「值得照著做」。")
        add("後者要看下面的 LLM Judge，以及人工抽樣。")
    else:
        for case in failures:
            add(f"### `{case.case_id}`　{'、'.join(case.tags)}")
            add("")
            for result in case.failures:
                add(f"- **{CRITERIA_LABELS.get(result.name, result.name)}**：{result.detail}")
            add("")
            add("```")
            add(f"下一步：{case.suggestion.get('next_action', '')}")
            add(f"時機：　{case.suggestion.get('suggested_timing', '')}")
            add(f"話術：　{case.suggestion.get('talking_point', '')}")
            add(f"引用：　{case.suggestion.get('evidence', [])}")
            add("```")
            add("")
    add("")

    # --- LLM Judge ---
    add("## LLM Judge（第二層）")
    add("")
    if not judged:
        add("這一輪沒有跑 Judge（加上 `--judge` 才會跑，會多花一次 API 費用）。")
    else:
        judged_cases = [c for c in report.cases if c.judge]
        add("| 案例 | 語氣自然 | 動作具體 | 沒有捏造 | 判官的話 |")
        add("|---|---|---|---|---|")
        for case in judged_cases:
            j = case.judge or {}
            add(
                f"| `{case.case_id}` | {'✅' if j.get('tone_natural') else '❌'} | "
                f"{'✅' if j.get('action_specific') else '❌'} | "
                f"{'✅' if j.get('no_fabrication') else '❌'} | "
                f"{(j.get('comment') or '').replace('|', '／')} |"
            )
        add("")
        add("**Judge 的結果只能拿來看趨勢，不能當成事實。**")
        add("判官本身也是同一類模型，它會出錯，")
        add("而且它的錯誤跟被評估的模型可能是相關的 —— 同樣的偏好、同樣的盲點。")
        add("要引用 Judge 的數字，前提是先人工抽樣校準過它跟人的一致率。")
    add("")

    # --- 成本 ---
    add("## 成本與延遲")
    add("")
    add(f"- Prompt tokens：{report.prompt_tokens:,}")
    add(f"- Completion tokens：{report.completion_tokens:,}")
    add(
        f"- 延遲中位數：{report.median_latency_ms} ms"
        if report.median_latency_ms is not None
        else "- 延遲中位數：—"
    )
    if report.failed_cases:
        add("")
        add("### 執行失敗（不計入統計）")
        add("")
        for case_id, reason in report.failed_cases:
            add(f"- `{case_id}`：{reason}")
        add("")
        add("失敗的案例不併進統計：逾時是基礎設施問題，")
        add("跟模型寫出一句捏造的話是兩回事，混在一起算會讓數字無法解讀。")
    add("")

    # --- 人工抽樣 ---
    add("## 第三層：人工抽樣")
    add("")
    add("前兩層都不回答最後那個問題：**業務會不會照著這則建議打電話。**")
    add("")
    add("那個問題只有人能回答，而且只能抽樣 —— 全量人工複核的成本，")
    add("比這個功能省下來的時間還高。建議的做法是每次改 prompt 之後抽 5 則，")
    add("由具業務經驗的人給「可用／要改／不能用」三檔，")
    add("同時記錄他跟 Judge 判斷不一致的那幾則，那是 Judge 的校準資料。")
    add("")

    return "\n".join(lines)
