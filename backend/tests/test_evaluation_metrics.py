"""評估指標的單元測試。

為什麼評估程式也要測？因為**一份算錯的準確率比沒有準確率更糟** ——
它會讓人對著錯的方向調 prompt，而且錯得很難察覺
（數字看起來總是「合理」的，沒人會懷疑 87.3% 是算錯的）。

這裡不呼叫 OpenAI，測的純粹是比對與統計邏輯。
"""

import pytest

from evaluation.metrics import (
    FIELDS,
    CaseResult,
    Outcome,
    build_report,
    classify,
    compare_case,
    is_empty,
)


def _expected(**overrides) -> dict:
    base = {name: None for name in FIELDS}
    base["budget_is_approximate"] = False
    base.update(overrides)
    return base


def _case(case_id: str, expected: dict, actual: dict) -> CaseResult:
    return CaseResult(
        case_id=case_id,
        raw_requirement="（測試用）",
        tags=[],
        expected=expected,
        actual=actual,
        outcomes=compare_case(expected, actual),
    )


# ---------------------------------------------------------------- 四種結果的判定


@pytest.mark.parametrize(
    ("expected", "actual", "want"),
    [
        ("七期", "七期", Outcome.CORRECT),
        (None, None, Outcome.CORRECT),
        ("七期", None, Outcome.MISS),
        (None, "七期", Outcome.HALLUCINATION),
        ("七期", "信義區", Outcome.WRONG),
    ],
)
def test_classify_covers_four_outcomes(expected, actual, want):
    assert classify("location", expected, actual) is want


def test_hallucination_is_distinguished_from_wrong():
    """捏造與抽錯必須分開。

    「客戶沒提到預算，模型生了一個 2000 萬」跟
    「客戶說 2000 萬，模型抽成 200 萬」是兩種完全不同的問題：
    前者是在 CRM 裡製造假資訊，後者是換算錯誤。
    混在一起看，就不知道該修 prompt 的哪一段。
    """
    assert classify("budget_max", None, 20000000) is Outcome.HALLUCINATION
    assert classify("budget_max", 20000000, 2000000) is Outcome.WRONG


# ---------------------------------------------------------------- 空值的定義


def test_false_counts_as_empty_only_for_budget_is_approximate():
    """budget_is_approximate 的 false 等同「沒有這個資訊」，parking 的 false 不是。

    如果不這樣分，模型只要把每一筆 budget_is_approximate 都填 false，
    就能在那個欄位刷到很高的分數 —— 而那什麼也沒說明。

    parking 的 false 則是客戶明確說「不用車位」，是真正的資訊，答對就該算答對。
    """
    assert is_empty("budget_is_approximate", False) is True
    assert is_empty("parking", False) is False

    # 客戶沒講預算語氣，模型硬標成「概數」→ 捏造
    assert classify("budget_is_approximate", False, True) is Outcome.HALLUCINATION
    # 客戶明確說不用車位，模型也答 false → 這是抽對了
    assert classify("parking", False, False) is Outcome.CORRECT


def test_always_answering_false_does_not_inflate_recall():
    """一個永遠回 false 的模型，在 budget_is_approximate 上的 recall 必須是 0。"""
    cases = [
        _case(
            f"case-{i}",
            _expected(budget_is_approximate=True, budget_max=20000000),
            _expected(budget_is_approximate=False, budget_max=20000000),
        )
        for i in range(5)
    ]
    report = build_report(model="m", prompt_version="v", cases=cases)

    stats = report.per_field["budget_is_approximate"]
    assert stats.recall == 0.0
    assert stats.miss == 5


# ---------------------------------------------------------------- 統計彙總


def test_field_accuracy_counts_every_field_of_every_case():
    """一筆全對、一筆錯一個欄位 → 兩筆的欄位總數裡只錯一個。

    分母用 len(FIELDS) 推導而不是寫死數字：
    日後再加欄位時，這個測試該驗的性質沒變，不該因為算術而紅。
    """
    cases = [
        _case("case-1", _expected(location="七期"), _expected(location="七期")),
        _case("case-2", _expected(location="信義區"), _expected(location="大安區")),
    ]
    report = build_report(model="m", prompt_version="v", cases=cases)

    total = 2 * len(FIELDS)
    assert report.field_accuracy == pytest.approx((total - 1) / total)


def test_exact_match_rate_requires_every_field():
    """完全正確率是最嚴格的指標：錯一個欄位，整筆就不算對。"""
    cases = [
        _case("case-1", _expected(rooms=3), _expected(rooms=3)),
        _case("case-2", _expected(rooms=3, location="七期"), _expected(rooms=3)),
    ]
    report = build_report(model="m", prompt_version="v", cases=cases)

    assert report.exact_match_rate == pytest.approx(0.5)


def test_hallucination_rate_is_measured_against_empty_fields_only():
    """捏造率的分母是「客戶沒提到的欄位數」，不是全部欄位數。

    用全部欄位當分母會把這個數字稀釋掉：
    客戶講了很多的案例會讓捏造率看起來變低，但模型的行為根本沒變。
    """
    # 客戶只講了房數，其餘欄位都是空的；模型多生了一個 location
    case = _case("case-1", _expected(rooms=3), _expected(rooms=3, location="七期"))
    report = build_report(model="m", prompt_version="v", cases=[case])

    # 分母是「空欄位數」（總欄位減掉有值的 rooms），不是全部欄位
    empty_fields = len(FIELDS) - 1
    assert report.hallucination_rate == pytest.approx(1 / empty_fields)


def test_precision_and_recall_are_none_when_there_is_nothing_to_measure():
    """沒有任何案例提到某個欄位時，該欄位的 recall 是「無從得知」而不是 0。

    回 0 會讓報告出現「purpose recall 0%」這種誤導性的結論 ——
    實際上只是資料集裡沒有考到它。
    """
    case = _case("case-1", _expected(), _expected())
    report = build_report(model="m", prompt_version="v", cases=[case])

    stats = report.per_field["purpose"]
    assert stats.recall is None
    assert stats.precision is None
    assert stats.accuracy == 1.0


def test_failed_cases_are_kept_out_of_the_accuracy_numbers():
    """逾時失敗不能算成「答錯」。

    那是基礎設施問題，跟模型理解錯誤是兩回事，
    混進去會讓準確率變得無法解讀（分數低到底是模型爛還是網路不穩？）。
    """
    case = _case("case-1", _expected(rooms=3), _expected(rooms=3))
    report = build_report(
        model="m",
        prompt_version="v",
        cases=[case],
        failed_cases=[("case-2", "呼叫逾時")],
    )

    assert report.field_accuracy == 1.0
    assert report.exact_match_rate == 1.0
    assert len(report.failed_cases) == 1


def test_median_latency_and_token_totals():
    report = build_report(
        model="m",
        prompt_version="v",
        cases=[],
        prompt_tokens=800,
        completion_tokens=60,
        latencies_ms=[1000, 2000, 3000],
    )

    assert report.median_latency_ms == 2000
    assert report.prompt_tokens + report.completion_tokens == 860


# ---------------------------------------------------------------- 資料集本身


DATASET_FILES = ("dataset.json", "holdout.json", "final_test.json")

# final_test.json 是取材自真實業務場景的句子，不是照規則造出來的，
# 所以有幾個欄位天然沒被考到 —— 真實客戶很少講預算區間，
# 講的時間也多半是工作行程而不是購屋時程。
# 這是這份資料的事實，不是它的缺陷，所以在覆蓋率檢查上豁免這幾欄，
# 並把原因記在該檔的 meta.known_coverage_gaps 裡。
COVERAGE_EXEMPT = {
    "final_test.json": {"budget_min", "purchase_timeline", "budget_is_approximate"},
}


def _load(filename: str) -> dict:
    import json
    import pathlib

    path = pathlib.Path(__file__).resolve().parents[1] / "evaluation" / filename
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("filename", DATASET_FILES)
def test_dataset_is_well_formed(filename):
    """資料集的每一筆都要有 FIELDS 裡的每一個欄位標註。

    少標一個欄位不會讓程式壞掉，只會讓那個欄位被當成 null 靜靜地算進統計，
    然後產出一個沒人發現是錯的準確率。所以這裡要擋住。
    """
    from app.models.enums import PropertyType, Purpose

    dataset = _load(filename)
    cases = dataset["cases"]

    assert len(cases) == dataset["meta"]["case_count"]

    seen_ids = set()
    for case in cases:
        assert case["id"] not in seen_ids, f"{case['id']} 重複"
        seen_ids.add(case["id"])

        assert case["raw_requirement"].strip(), f"{case['id']} 原話是空的"
        assert set(case["expected"]) == set(FIELDS), f"{case['id']} 欄位不齊"

        expected = case["expected"]
        assert isinstance(expected["budget_is_approximate"], bool)

        if expected["property_type"] is not None:
            assert expected["property_type"] in {t.value for t in PropertyType}
        if expected["purpose"] is not None:
            assert expected["purpose"] in {p.value for p in Purpose}

        low, high = expected["budget_min"], expected["budget_max"]
        if low is not None and high is not None:
            assert low <= high, f"{case['id']} 預算下限大於上限"

        if expected["budget_is_approximate"]:
            assert low is not None or high is not None, (
                f"{case['id']} 標成概數卻沒有預算數字"
            )


@pytest.mark.parametrize("filename", DATASET_FILES)
def test_dataset_covers_every_field_with_a_real_value(filename):
    """每個欄位都至少要有幾筆非空的正確答案。

    否則那個欄位的 recall 會是 None，等於根本沒被評估到 ——
    報告上看起來有那一列，實際上什麼都沒量。
    """
    cases = _load(filename)["cases"]
    exempt = COVERAGE_EXEMPT.get(filename, set())

    for name in FIELDS:
        if name in exempt:
            continue
        filled = sum(
            1 for c in cases if not is_empty(name, c["expected"].get(name))
        )
        assert filled >= 3, f"{filename} 的欄位 {name} 只有 {filled} 筆非空答案，樣本太少"


def test_coverage_exemptions_are_documented():
    """豁免不能是偷偷加的，一定要在資料集裡寫明原因。

    否則日後看到報告上某欄位的 Recall 是「—」，
    會分不清是「這份資料沒考到」還是「有人把它偷偷關掉了」。
    """
    for filename, exempt in COVERAGE_EXEMPT.items():
        gaps = _load(filename)["meta"].get("known_coverage_gaps", [])
        text = " ".join(gaps)
        for name in exempt:
            assert name in text, f"{filename} 豁免了 {name} 卻沒有記錄原因"


def test_demo_data_does_not_reuse_evaluation_sentences():
    """Demo 客戶的原話不能跟任何一份評估資料集重複。

    重複的話，那些測試句子就會躺在 Demo 資料庫裡被反覆分析、被反覆看到答案，
    「從沒被用來調整過任何東西」這個前提會慢慢失效 ——
    尤其 final_test 是鎖到 Sprint 7 才開的期末考。

    Demo 資料可以「參考」測試句子的風格，但不能重用句子本身。
    """
    from app.services.starter_data import STARTER_LEADS
    from scripts.seed_demo import LEADS

    # 兩邊都要守：demo 帳號那 32 筆，以及註冊時自動建立的範例客戶。
    # 兩份資料分開寫（目的不同），但這條紀律是同一條。
    written = {spec["raw"] for spec in LEADS} | {
        spec["raw"] for spec in STARTER_LEADS
    }
    for name in DATASET_FILES:
        overlap = written & {c["raw_requirement"] for c in _load(name)["cases"]}
        assert overlap == set(), f"Demo／範例資料與 {name} 重複：{overlap}"


def test_no_sentence_appears_in_two_datasets():
    """三份資料集不能有重複的句子。

    只要有一句重疊，holdout 與 final_test 就不再是「模型沒看過的題目」，
    它們的分數也就失去了「這是誠實數字」的意義。
    """
    import itertools

    sentences = {
        name: {c["raw_requirement"] for c in _load(name)["cases"]}
        for name in DATASET_FILES
    }
    for a, b in itertools.combinations(DATASET_FILES, 2):
        assert sentences[a] & sentences[b] == set(), f"{a} 與 {b} 有重複句子"
