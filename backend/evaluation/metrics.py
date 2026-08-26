"""評估指標的計算。

這個檔案不碰網路、不碰資料庫、不碰 OpenAI，純粹是「比對兩個 dict 然後算數字」。
刻意獨立出來，是因為**評估程式本身也會寫錯**，
而一份算錯的準確率比沒有準確率更糟 —— 它會讓人對著錯的方向調 prompt。
所以它有自己的單元測試（tests/test_evaluation_metrics.py）。

## 為什麼不能只看 accuracy

資料集裡大量欄位的正確答案是 null（客戶本來就沒提到那麼多事）。
一個永遠回 null 的模型，光靠猜空值就能拿到很漂亮的 accuracy。
所以每個欄位除了 accuracy，還要拆出四種結果：

| 結果 | 意思 | 為什麼要分開看 |
|---|---|---|
| CORRECT | 答對（包含正確地答 null） | |
| MISS | 客戶有講，模型漏抽 | 資料變少，業務得自己補 |
| HALLUCINATION | 客戶沒講，模型自己生一個 | **最嚴重**：CRM 裡出現客戶從沒說過的資訊 |
| WRONG | 兩邊都有值但不一樣 | 通常是單位換算或語意判斷錯誤 |

規劃書 Phase 13 明確要求「避免捏造不存在資訊」，HALLUCINATION 就是它的量化版本。
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from enum import Enum

# 順序固定，報告裡的欄位排列才不會每次都跳動
FIELDS: tuple[str, ...] = (
    "location",
    "budget_min",
    "budget_max",
    "budget_is_approximate",
    "rooms",
    "property_type",
    "building_age_max",
    "parking",
    "purpose",
    "purchase_timeline",
    "urgency",
)

# budget_is_approximate 是 bool，沒有 null。
# 但它的 false 在語意上等同「沒有這個資訊」（客戶沒講預算，或講的是精確數字），
# 所以計分時要把 false 視為空值 —— 否則模型把每一筆都標成 false 就能刷高分。
#
# parking 的 false 不同：那是客戶明確說「不用車位」，是真正的資訊。
EMPTY_IS_FALSE: frozenset[str] = frozenset({"budget_is_approximate"})


class Outcome(str, Enum):
    CORRECT = "CORRECT"
    MISS = "MISS"
    HALLUCINATION = "HALLUCINATION"
    WRONG = "WRONG"


def is_empty(field_name: str, value: object) -> bool:
    """這個值算不算「沒有資訊」。"""
    if value is None:
        return True
    return field_name in EMPTY_IS_FALSE and value is False


def classify(field_name: str, expected: object, actual: object) -> Outcome:
    """比對單一欄位，判斷屬於四種結果的哪一種。"""
    expected_empty = is_empty(field_name, expected)
    actual_empty = is_empty(field_name, actual)

    if expected_empty and actual_empty:
        return Outcome.CORRECT
    if expected_empty:
        return Outcome.HALLUCINATION
    if actual_empty:
        return Outcome.MISS
    return Outcome.CORRECT if expected == actual else Outcome.WRONG


def compare_case(
    expected: dict[str, object], actual: dict[str, object]
) -> dict[str, Outcome]:
    """比對一整筆案例的 10 個欄位。"""
    return {
        name: classify(name, expected.get(name), actual.get(name)) for name in FIELDS
    }


@dataclass
class FieldStats:
    """單一欄位在整個資料集上的表現。"""

    # 答對，且答案是實際的值（不是 null）
    correct_filled: int = 0
    # 答對，但答案是 null —— 分開計數是為了讓「靠猜 null 拿到的分數」無所遁形
    correct_empty: int = 0
    miss: int = 0
    hallucination: int = 0
    wrong: int = 0

    @property
    def total(self) -> int:
        return (
            self.correct_filled
            + self.correct_empty
            + self.miss
            + self.hallucination
            + self.wrong
        )

    @property
    def correct(self) -> int:
        return self.correct_filled + self.correct_empty

    @property
    def accuracy(self) -> float | None:
        return self.correct / self.total if self.total else None

    @property
    def recall(self) -> float | None:
        """客戶真的有講的那些欄位裡，抽對了幾成。"""
        denominator = self.correct_filled + self.miss + self.wrong
        return self.correct_filled / denominator if denominator else None

    @property
    def precision(self) -> float | None:
        """模型填了值的那些欄位裡，有幾成是對的。"""
        denominator = self.correct_filled + self.hallucination + self.wrong
        return self.correct_filled / denominator if denominator else None

    def add(self, outcome: Outcome, expected_is_empty: bool) -> None:
        if outcome is Outcome.CORRECT:
            if expected_is_empty:
                self.correct_empty += 1
            else:
                self.correct_filled += 1
        elif outcome is Outcome.MISS:
            self.miss += 1
        elif outcome is Outcome.HALLUCINATION:
            self.hallucination += 1
        else:
            self.wrong += 1


@dataclass
class CaseResult:
    """一筆案例的評估結果。"""

    case_id: str
    raw_requirement: str
    tags: list[str]
    expected: dict[str, object]
    actual: dict[str, object]
    outcomes: dict[str, Outcome]

    @property
    def is_exact_match(self) -> bool:
        """所有欄位全對。這是最嚴格、也最貼近使用者感受的指標。"""
        return all(o is Outcome.CORRECT for o in self.outcomes.values())

    def errors(self) -> dict[str, Outcome]:
        return {f: o for f, o in self.outcomes.items() if o is not Outcome.CORRECT}


@dataclass
class Report:
    """整份評估報告的數字部分。"""

    model: str
    prompt_version: str
    per_field: dict[str, FieldStats] = dataclass_field(default_factory=dict)
    cases: list[CaseResult] = dataclass_field(default_factory=list)
    failed_cases: list[tuple[str, str]] = dataclass_field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latencies_ms: list[int] = dataclass_field(default_factory=list)

    @property
    def field_accuracy(self) -> float | None:
        """所有欄位攤平之後的整體正確率。"""
        correct = sum(s.correct for s in self.per_field.values())
        total = sum(s.total for s in self.per_field.values())
        return correct / total if total else None

    @property
    def exact_match_rate(self) -> float | None:
        if not self.cases:
            return None
        return sum(1 for c in self.cases if c.is_exact_match) / len(self.cases)

    @property
    def hallucination_rate(self) -> float | None:
        """在「客戶沒提到」的欄位裡，模型憑空生出資訊的比例。"""
        hallucinations = sum(s.hallucination for s in self.per_field.values())
        opportunities = sum(
            s.correct_empty + s.hallucination for s in self.per_field.values()
        )
        return hallucinations / opportunities if opportunities else None

    @property
    def median_latency_ms(self) -> int | None:
        if not self.latencies_ms:
            return None
        ordered = sorted(self.latencies_ms)
        return ordered[len(ordered) // 2]


def build_report(
    *,
    model: str,
    prompt_version: str,
    cases: list[CaseResult],
    failed_cases: list[tuple[str, str]] | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    latencies_ms: list[int] | None = None,
) -> Report:
    per_field = {name: FieldStats() for name in FIELDS}

    for case in cases:
        for name, outcome in case.outcomes.items():
            per_field[name].add(
                outcome, is_empty(name, case.expected.get(name))
            )

    return Report(
        model=model,
        prompt_version=prompt_version,
        per_field=per_field,
        cases=cases,
        failed_cases=failed_cases or [],
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latencies_ms=latencies_ms or [],
    )
