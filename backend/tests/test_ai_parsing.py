"""AI 需求解析的測試。

**這裡不會呼叫真正的 OpenAI。**

理由有三個：花錢、慢、而且模型有隨機性 —— 同一句話兩次跑出不同結果，
測試就會時紅時綠，久了大家就開始忽略紅燈。

所以這裡測的是「我們寫的程式對不對」：
驗證有沒有生效、失敗時 CRM 有沒有被牽連、AI 回 null 會不會蓋掉業務填的資料。

至於「AI 準不準」，那是 Sprint 4 Evaluation 的職責，用一套獨立的評估資料集來量。
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_ai_service
from app.main import app
from app.services.ai_service import AIService
from app.services.llm_provider import LLMError, LLMResponse

PREFIX = "/api/v1"

# 客戶什麼都沒提到的樣子：每個欄位都是 null。
# strict schema 要求所有欄位都必須出現，所以「沒提到」是 null，不是省略。
EMPTY_RESULT = {
    "location": None,
    "budget_min": None,
    "budget_max": None,
    "budget_is_approximate": False,
    "rooms": None,
    "property_type": None,
    "building_age_max": None,
    "parking": None,
    "purpose": None,
    "purchase_timeline": None,
    "urgency": None,
}


def _json_with(**fields) -> str:
    """組出一份假的模型回應。只寫想測的欄位，其餘一律 null。"""
    return json.dumps({**EMPTY_RESULT, **fields})


# 一份「客戶什麼都說了」的完整回應，當作多數測試的基準
FULL_JSON = _json_with(
    location="七期",
    budget_max=20000000,
    budget_is_approximate=True,
    rooms=3,
    property_type="ELEVATOR_BUILDING",
    building_age_max=10,
    parking=True,
    purpose="SELF_USE",
    purchase_timeline=3,
    urgency="HIGH",
)


class FakeLLMProvider:
    """假的 LLM。

    不需要繼承 LLMProvider —— 那是個 Protocol，方法簽名對得上就能用。
    這正是當初把 provider 切出來的目的。
    """

    def __init__(self, content: str = FULL_JSON, error: Exception | None = None):
        self.content = content
        self.error = error
        self.calls: list[dict] = []

    @property
    def model_name(self) -> str:
        return "fake-model"

    def complete_json(self, **kwargs) -> LLMResponse:
        # 把呼叫參數留下來，測試才能檢查 prompt 裡真的帶了客戶原話
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return LLMResponse(
            content=self.content,
            model="fake-model",
            prompt_tokens=100,
            completion_tokens=50,
        )


@pytest.fixture
def fake_llm() -> FakeLLMProvider:
    return FakeLLMProvider()


@pytest.fixture
def ai_client(client: TestClient, fake_llm: FakeLLMProvider) -> TestClient:
    """已登入，而且 AI 已被換成假的。"""
    app.dependency_overrides[get_ai_service] = lambda: AIService(fake_llm)
    return client


def _create_lead(c: TestClient, **overrides) -> dict:
    payload = {"name": "王先生", "raw_requirement": "想在七期找三房，預算 2000 萬左右"}
    payload.update(overrides)
    resp = c.post(f"{PREFIX}/leads", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------- 正常流程


def test_analyze_writes_parsed_fields_back_to_lead(ai_client, fake_llm):
    lead = _create_lead(ai_client)

    resp = ai_client.post(f"{PREFIX}/leads/{lead['id']}/analyze")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["lead"]["location"] == "七期"
    assert body["lead"]["budget_max"] == 20000000
    assert body["lead"]["budget_is_approximate"] is True
    assert body["lead"]["rooms"] == 3
    assert body["lead"]["property_type"] == "ELEVATOR_BUILDING"
    assert body["lead"]["building_age_max"] == 10
    assert body["lead"]["purchase_timeline"] == 3
    assert body["lead"]["urgency"] == "HIGH"

    # 客戶原話是唯一事實來源，任何情況下都不該被解析結果覆蓋
    assert body["lead"]["raw_requirement"] == lead["raw_requirement"]


def test_analyze_records_metadata_for_later_evaluation(ai_client):
    lead = _create_lead(ai_client)

    analysis = ai_client.post(f"{PREFIX}/leads/{lead['id']}/analyze").json()["analysis"]

    # prompt_version 與 model 是 Sprint 4 拿來比較「換了之後有沒有比較準」的依據。
    # 這裡刻意寫死版號而不是引用 DEFAULT_PROMPT_VERSION：
    # 改了預設版本就該讓這個測試紅一次，逼人確認「這次改版有跑過評估嗎」。
    assert analysis["prompt_version"] == "lead_analysis_v4"
    assert analysis["model"] == "fake-model"
    assert analysis["prompt_tokens"] == 100
    assert analysis["completion_tokens"] == 50
    assert analysis["latency_ms"] is not None
    assert analysis["parsed_result"]["location"] == "七期"


def test_prompt_version_is_selectable_and_recorded(fake_llm):
    """舊版 prompt 要能被選來跑，而且紀錄裡存的是實際用的那一版。

    這是 Sprint 4 能做 A/B 比較的前提：兩個版本跑同一份資料集，
    數字才擺得到一起。存錯版號的話，比較出來的結論就是錯的。
    """
    from app.services.ai_service import PROMPT_V1, AIService

    service = AIService(fake_llm, prompt_version=PROMPT_V1)
    outcome = service.parse_requirement("七期三房")

    assert outcome.prompt_version == PROMPT_V1
    # 送出去的真的是 v1 的內容，不是預設那一版
    assert fake_llm.calls[0]["system_prompt"].endswith('「想找信義區」→ "信義區"\n')


def test_unknown_prompt_version_is_rejected_at_construction(fake_llm):
    """打錯版號要當場爆掉，而不是安靜地用預設版本跑完整份評估。"""
    from app.services.ai_service import AIService

    with pytest.raises(ValueError, match="未知的 prompt 版本"):
        AIService(fake_llm, prompt_version="lead_analysis_v99")


def test_analyze_sends_raw_requirement_to_the_model(ai_client, fake_llm):
    lead = _create_lead(ai_client, raw_requirement="想找信義區兩房")

    ai_client.post(f"{PREFIX}/leads/{lead['id']}/analyze")

    assert len(fake_llm.calls) == 1
    assert "信義區兩房" in fake_llm.calls[0]["user_prompt"]
    # strict 必須是開的，否則 structured output 只是「拜託模型回 JSON」
    assert fake_llm.calls[0]["json_schema"]["additionalProperties"] is False


def test_detail_page_exposes_latest_analysis(ai_client):
    lead = _create_lead(ai_client)
    ai_client.post(f"{PREFIX}/leads/{lead['id']}/analyze")

    detail = ai_client.get(f"{PREFIX}/leads/{lead['id']}").json()

    # 前端靠這個決定要不要掛「AI 解析」徽章，重新整理後徽章才不會消失
    assert detail["latest_analysis"]["prompt_version"] == "lead_analysis_v4"


def test_latest_analysis_is_none_before_any_analysis(ai_client):
    lead = _create_lead(ai_client)

    detail = ai_client.get(f"{PREFIX}/leads/{lead['id']}").json()

    assert detail["latest_analysis"] is None


# ---------------------------------------------------------------- 不覆蓋既有資料


def test_null_from_ai_does_not_erase_manually_entered_values(ai_client, fake_llm):
    """AI 回 null 代表「客戶沒提到」，不代表「業務填錯了」。

    這是整個功能最容易讓人不敢再按第二次的地方：
    業務手動填好的資料，被一次 AI 解析清空。
    """
    lead = _create_lead(ai_client, location="信義區", rooms=4)
    fake_llm.content = _json_with()

    updated = ai_client.post(f"{PREFIX}/leads/{lead['id']}/analyze").json()["lead"]

    assert updated["location"] == "信義區"
    assert updated["rooms"] == 4


def test_default_false_approximate_does_not_overwrite_existing_flag(ai_client, fake_llm):
    """沒抽到預算時，budget_is_approximate 的 false 只是預設值，不是判斷結果。"""
    lead = _create_lead(ai_client, budget_max=20000000)
    # 新增客戶時不開放這個欄位（它要讀過原話才知道），所以用 PATCH 設定
    ai_client.patch(f"{PREFIX}/leads/{lead['id']}", json={"budget_is_approximate": True})
    fake_llm.content = _json_with(location="七期")

    updated = ai_client.post(f"{PREFIX}/leads/{lead['id']}/analyze").json()["lead"]

    assert updated["budget_is_approximate"] is True


# ---------------------------------------------------------------- 失敗處理


def test_lead_without_raw_requirement_returns_422(ai_client):
    """沒有原話可分析是使用者的輸入問題（422），不是 AI 壞了（503）。

    分開回應，前端才知道要顯示「請先填寫客戶需求」還是「請稍後重試」。
    """
    lead = _create_lead(ai_client, raw_requirement=None)

    resp = ai_client.post(f"{PREFIX}/leads/{lead['id']}/analyze")

    assert resp.status_code == 422


def test_blank_raw_requirement_returns_422(ai_client):
    lead = _create_lead(ai_client, raw_requirement="   ")

    assert ai_client.post(f"{PREFIX}/leads/{lead['id']}/analyze").status_code == 422


def test_llm_failure_returns_503_and_leaves_lead_untouched(ai_client, fake_llm):
    """AI 掛掉不能牽連 CRM —— 客戶資料必須完好如初。"""
    lead = _create_lead(ai_client, location="信義區")
    fake_llm.error = LLMError("OpenAI 逾時")

    resp = ai_client.post(f"{PREFIX}/leads/{lead['id']}/analyze")
    assert resp.status_code == 503

    after = ai_client.get(f"{PREFIX}/leads/{lead['id']}").json()
    assert after["location"] == "信義區"
    assert after["latest_analysis"] is None


@pytest.mark.parametrize(
    ("field", "bad_value", "why"),
    [
        ("budget_max", -5000, "預算是負數"),
        ("budget_max", 99999999999999, "多打了好幾個零"),
        ("rooms", 99, "房數不合理"),
        ("building_age_max", 500, "屋齡 500 年"),
        ("purchase_timeline", 9999, "時程超過十年"),
    ],
)
def test_unreasonable_values_are_rejected(ai_client, fake_llm, field, bad_value, why):
    """strict schema 保證「結構正確」，Pydantic 保證「值合理」。

    這幾個回應在 JSON Schema 眼中完全合法（都是 integer），
    擋下它們的是 Pydantic 的數值範圍檢查。這就是第二道關卡存在的理由。
    """
    lead = _create_lead(ai_client)
    fake_llm.content = _json_with(**{field: bad_value})

    resp = ai_client.post(f"{PREFIX}/leads/{lead['id']}/analyze")

    assert resp.status_code == 503, f"{why} 應該要被擋下來"


def test_budget_min_greater_than_max_is_rejected(ai_client, fake_llm):
    lead = _create_lead(ai_client)
    fake_llm.content = _json_with(budget_min=30000000, budget_max=20000000)

    assert ai_client.post(f"{PREFIX}/leads/{lead['id']}/analyze").status_code == 503


def test_malformed_json_is_rejected(ai_client, fake_llm):
    lead = _create_lead(ai_client)
    fake_llm.content = "這不是 JSON"

    assert ai_client.post(f"{PREFIX}/leads/{lead['id']}/analyze").status_code == 503


def test_returns_503_when_ai_is_not_configured(client):
    """沒設 OPENAI_API_KEY 的環境（例如 CI）仍要能跑完整個 CRM，只是這顆按鈕不能用。"""
    app.dependency_overrides[get_ai_service] = lambda: None
    lead = _create_lead(client)

    assert client.post(f"{PREFIX}/leads/{lead['id']}/analyze").status_code == 503


# ---------------------------------------------------------------- 權限


def test_analyze_requires_login(anon_client, fake_llm):
    app.dependency_overrides[get_ai_service] = lambda: AIService(fake_llm)

    assert anon_client.post(f"{PREFIX}/leads/1/analyze").status_code == 401


def test_cannot_analyze_someone_elses_lead(ai_client, other_client):
    """回 404 而不是 403：403 等於承認「這個 id 存在，只是不給你看」。"""
    lead = _create_lead(ai_client)

    assert other_client.post(f"{PREFIX}/leads/{lead['id']}/analyze").status_code == 404


# ---------------------------------------------------------------- 原話快照快取
#
# 同一段原話重複解析，結果本來就會一樣 —— 那是純粹的浪費，而且是**花錢的**浪費。
# 所以比對的是原話的內容，不是「按過幾次」：改了原話再按，仍然要真的重新解析。


def test_same_raw_requirement_does_not_call_the_model_twice(ai_client, fake_llm):
    lead = _create_lead(ai_client)

    first = ai_client.post(f"{PREFIX}/leads/{lead['id']}/analyze").json()
    second = ai_client.post(f"{PREFIX}/leads/{lead['id']}/analyze").json()

    assert len(fake_llm.calls) == 1, "原話沒變，不應該再呼叫一次模型"
    assert first["reused"] is False
    assert second["reused"] is True
    # 沿用的是同一筆分析紀錄，不是新增一筆內容相同的
    assert second["analysis"]["id"] == first["analysis"]["id"]


def test_editing_the_raw_requirement_triggers_a_real_reanalysis(ai_client, fake_llm):
    """客戶需求變了，業務改了原話 —— 這是新的輸入，該重跑。"""
    lead = _create_lead(ai_client)
    ai_client.post(f"{PREFIX}/leads/{lead['id']}/analyze")

    ai_client.patch(
        f"{PREFIX}/leads/{lead['id']}",
        json={"raw_requirement": "改成想找兩房，預算提高到 2500 萬"},
    )
    again = ai_client.post(f"{PREFIX}/leads/{lead['id']}/analyze").json()

    assert len(fake_llm.calls) == 2
    assert again["reused"] is False
    assert fake_llm.calls[-1] != fake_llm.calls[0]


def test_reused_analysis_does_not_overwrite_manual_corrections(ai_client, fake_llm):
    """快取命中時不重新套用欄位。

    AI 把房數抽錯、業務手動改對了，這時再按一次「AI 解析」，
    不可以把他改對的東西蓋回 AI 原本的錯誤 ——
    他按那顆按鈕並沒有要求系統做這件事。
    """
    fake_llm.content = _json_with(rooms=3)
    lead = _create_lead(ai_client)
    ai_client.post(f"{PREFIX}/leads/{lead['id']}/analyze")

    ai_client.patch(f"{PREFIX}/leads/{lead['id']}", json={"rooms": 2})
    again = ai_client.post(f"{PREFIX}/leads/{lead['id']}/analyze").json()

    assert again["reused"] is True
    assert again["lead"]["rooms"] == 2


def test_failed_analysis_is_not_cached(ai_client, fake_llm):
    """AI 掛掉時不會留下分析紀錄，所以重試永遠打得出去。

    這一條是快取最重要的邊界：如果連失敗都被記住，
    業務就會卡在一個「重試按鈕按了沒反應」的狀態。
    """
    fake_llm.error = LLMError("模型暫時無法使用")
    lead = _create_lead(ai_client)

    assert ai_client.post(f"{PREFIX}/leads/{lead['id']}/analyze").status_code == 503

    fake_llm.error = None
    retried = ai_client.post(f"{PREFIX}/leads/{lead['id']}/analyze").json()

    assert retried["reused"] is False
    assert len(fake_llm.calls) == 2


def test_cache_is_per_lead(ai_client, fake_llm):
    """兩位客戶剛好講了一模一樣的話，也要各自解析。

    快取的鍵是「這位客戶的上一次解析」，不是全域的原話對照表 ——
    後者會讓一筆客戶的分析紀錄掛到另一筆身上。
    """
    first = _create_lead(ai_client, name="王先生")
    second = _create_lead(ai_client, name="李小姐")

    ai_client.post(f"{PREFIX}/leads/{first['id']}/analyze")
    other = ai_client.post(f"{PREFIX}/leads/{second['id']}/analyze").json()

    assert other["reused"] is False
    assert len(fake_llm.calls) == 2
