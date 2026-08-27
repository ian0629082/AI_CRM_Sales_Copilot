"""AI 跟進建議的測試。

跟 test_ai_parsing.py 一樣，**這裡不會呼叫真正的 OpenAI**。

但這個功能有一件事跟需求解析不同：它的輸出是自由文字，沒有標準答案。
所以這裡測的**不是**「建議寫得好不好」——那是 Criteria-based 評估的職責
（scripts/evaluate_followup.py），而且要用真的模型才量得出來。

這裡守的是程式層面的四件事：

1. context 真的有把互動紀錄與分數餵進去（少了它，AI 只能講空話）
2. 找不到出處的引用不會被端到業務面前
3. 產生建議不會改動客戶的任何欄位
4. AI 掛掉時 CRM 照常運作
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_follow_up_advisor
from app.main import app
from app.services.follow_up_advisor import FollowUpAdvisor
from app.services.llm_provider import LLMError, LLMResponse

PREFIX = "/api/v1"

RAW = "想在七期找三房，預算 2000 萬左右，我下個月要過去上班，所以有點急"


def _suggestion_json(**overrides) -> str:
    payload = {
        "next_action": "致電確認上週看的物件他考慮得如何",
        "talking_point": "陳先生您好，上次您提到下個月要過去上班，我這邊幫您留意了幾間七期的物件。",
        "suggested_timing": "明天上午",
        "evidence": ["下個月要過去上班"],
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


class FakeLLMProvider:
    """假的 LLM。跟 test_ai_parsing 用的是同一招：Protocol 只看方法簽名。"""

    def __init__(self, content: str | None = None, error: Exception | None = None):
        self.content = content if content is not None else _suggestion_json()
        self.error = error
        self.calls: list[dict] = []

    @property
    def model_name(self) -> str:
        return "fake-model"

    def complete_json(self, **kwargs) -> LLMResponse:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return LLMResponse(
            content=self.content,
            model="fake-model",
            prompt_tokens=300,
            completion_tokens=80,
        )


@pytest.fixture
def fake_llm() -> FakeLLMProvider:
    return FakeLLMProvider()


@pytest.fixture
def advice_client(client: TestClient, fake_llm: FakeLLMProvider) -> TestClient:
    app.dependency_overrides[get_follow_up_advisor] = lambda: FollowUpAdvisor(fake_llm)
    return client


def _create_lead(c: TestClient, **overrides) -> dict:
    payload = {"name": "陳先生", "phone": "0912345678", "raw_requirement": RAW}
    payload.update(overrides)
    resp = c.post(f"{PREFIX}/leads", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _add_interaction(c: TestClient, lead_id: int, content: str, type_="CALL") -> None:
    resp = c.post(
        f"{PREFIX}/leads/{lead_id}/interactions",
        json={"type": type_, "content": content},
    )
    assert resp.status_code == 201, resp.text


def _suggest(c: TestClient, lead_id: int):
    return c.post(f"{PREFIX}/leads/{lead_id}/follow-up-suggestion")


# ---------------------------------------------------------------- 正常流程


def test_suggestion_returns_three_sections(advice_client):
    lead = _create_lead(advice_client)

    resp = _suggest(advice_client, lead["id"])
    assert resp.status_code == 200, resp.text

    suggestion = resp.json()["suggestion"]["parsed_result"]
    assert suggestion["next_action"]
    assert suggestion["talking_point"]
    assert suggestion["suggested_timing"]


def test_context_carries_interactions_and_score(advice_client, fake_llm):
    """互動紀錄與分數必須真的出現在送給模型的 context 裡。

    這是這個功能的立身之本：如果 context 沒帶互動歷史，
    AI 講得出來的東西業務自己看客戶資料也講得出來，
    那就不值得為它付一次 API 費用。
    """
    lead = _create_lead(advice_client)
    _add_interaction(advice_client, lead["id"], "客戶說週末想看七期那間", "CALL")

    _suggest(advice_client, lead["id"])

    context = fake_llm.calls[0]["user_prompt"]
    assert "客戶說週末想看七期那間" in context
    assert "電話" in context  # 互動類型翻成中文，不是丟 CALL 給模型
    assert "意願分數" in context
    assert RAW in context


def test_metadata_and_score_snapshot_are_recorded(advice_client):
    """分數快照要存下來。

    分數會隨著業務補資料而變動。沒有快照的話，日後看到一則建議，
    分不出它是在「這位客戶還很冷」時給的，還是在他變成 HOT 之後給的。
    """
    lead = _create_lead(advice_client)

    body = _suggest(advice_client, lead["id"]).json()["suggestion"]

    assert body["analysis_type"] == "FOLLOW_UP"
    # 寫死版號而不是引用常數：改了預設 prompt 就該讓這個測試紅一次，
    # 逼人確認「這次改版有跑過評估嗎」。
    assert body["prompt_version"] == "follow_up_v4"
    assert body["model"] == "fake-model"
    assert body["prompt_tokens"] == 300
    assert body["latency_ms"] is not None
    assert body["score_snapshot"] == lead["lead_score"]
    assert body["level_snapshot"] == lead["lead_level"]


def test_plain_text_version_is_composed_for_later_use(advice_client):
    """純文字版本要拼好存著，Sprint 8 的 n8n 寄信時直接取用。"""
    lead = _create_lead(advice_client)

    text = _suggest(advice_client, lead["id"]).json()["suggestion"]["suggestion"]

    assert "下一步：" in text
    assert "建議話術：" in text
    assert "建議時機：" in text


def test_suggestion_is_visible_on_lead_detail(advice_client):
    """重新整理後建議還在，不必再花一次錢重產。"""
    lead = _create_lead(advice_client)
    _suggest(advice_client, lead["id"])

    detail = advice_client.get(f"{PREFIX}/leads/{lead['id']}").json()

    assert detail["latest_follow_up"] is not None
    assert detail["latest_follow_up"]["parsed_result"]["next_action"]


# ---------------------------------------------------------------- 捏造防線


def test_evidence_without_a_source_is_dropped(advice_client, fake_llm):
    """比對不到出處的引用不能端到業務面前。

    業務會直接照著念。一句「客戶說過的話」其實客戶從沒說過，
    打過去客戶當場就知道他沒在聽 —— 這比話術寫得平淡嚴重得多。
    """
    fake_llm.content = _suggestion_json(
        evidence=["下個月要過去上班", "他說預算可以拉到三千萬"]
    )
    lead = _create_lead(advice_client)

    body = _suggest(advice_client, lead["id"]).json()["suggestion"]

    assert body["parsed_result"]["evidence"] == ["下個月要過去上班"]


def test_evidence_may_come_from_interactions(advice_client, fake_llm):
    """互動紀錄跟客戶原話一樣，都是合法的引用來源。"""
    fake_llm.content = _suggestion_json(evidence=["週末想看七期那間"])
    lead = _create_lead(advice_client)
    _add_interaction(advice_client, lead["id"], "客戶說週末想看七期那間")

    body = _suggest(advice_client, lead["id"]).json()["suggestion"]

    assert body["parsed_result"]["evidence"] == ["週末想看七期那間"]


def test_too_many_quotes_are_truncated_not_rejected(advice_client, fake_llm):
    """引用超過 5 條要截斷，不能讓整則建議作廢。

    第一次真的連上模型，12 筆裡就有一筆回了 6 條而被擋下來，
    但「多引用一條」根本不是品質問題 —— 用整則作廢去處理一個排版偏好，
    使用者看到的是 503，而真正的原因只是模型多列了一項。
    """
    fake_llm.content = _suggestion_json(evidence=["下個月要過去上班"] * 6)
    lead = _create_lead(advice_client)

    resp = _suggest(advice_client, lead["id"])

    assert resp.status_code == 200
    assert len(resp.json()["suggestion"]["parsed_result"]["evidence"]) == 5


def test_paraphrased_evidence_counts_as_fabrication(advice_client, fake_llm):
    """改寫過的引用一律視為沒有出處。

    「下個月要去上班」跟原話「下個月要過去上班」意思一樣，但這裡仍然判失敗。
    一旦允許「意思差不多」，這個檢查就不再是逐字比對，
    也就不再守得住任何東西 —— 而它是這個功能唯一確定性的品質防線。
    """
    fake_llm.content = _suggestion_json(evidence=["下個月要去上班"])
    lead = _create_lead(advice_client)

    body = _suggest(advice_client, lead["id"]).json()["suggestion"]

    assert body["parsed_result"]["evidence"] == []


def test_whitespace_differences_do_not_count_as_fabrication(advice_client, fake_llm):
    """只有空白差異不算捏造，那是排版不是內容。"""
    fake_llm.content = _suggestion_json(evidence=["下個月 要過去上班"])
    lead = _create_lead(advice_client)

    body = _suggest(advice_client, lead["id"]).json()["suggestion"]

    assert body["parsed_result"]["evidence"] == ["下個月 要過去上班"]


# ---------------------------------------------------------------- 不該有的副作用


def test_suggestion_does_not_modify_the_lead(advice_client):
    """產生建議不會改動客戶的任何欄位，包括下次提醒日。

    建議是參考，不是系統替業務做的決定 ——
    「下次什麼時候聯絡」在 Sprint 5 就定案由業務自己填。
    """
    lead = _create_lead(advice_client)
    before = advice_client.get(f"{PREFIX}/leads/{lead['id']}").json()

    _suggest(advice_client, lead["id"])
    after = advice_client.get(f"{PREFIX}/leads/{lead['id']}").json()

    ignored = {"latest_follow_up", "updated_at"}
    assert {k: v for k, v in before.items() if k not in ignored} == {
        k: v for k, v in after.items() if k not in ignored
    }


def test_follow_up_does_not_hide_the_parsing_badge(advice_client, client):
    """產生建議之後，欄位上的「AI 解析」徽章不能消失。

    兩種分析共用 ai_analysis 這張表。若 latest_analysis 只取最新一筆，
    按過跟進建議之後徽章會全部不見 —— 因為最新那筆是建議，parsed_result 是 null。
    這個測試就是為了守住那個過濾條件。
    """
    from app.api.deps import get_ai_service
    from app.services.ai_service import AIService

    parsing_json = json.dumps(
        {
            "location": "七期",
            "budget_min": None,
            "budget_max": 20000000,
            "budget_is_approximate": True,
            "rooms": 3,
            "property_type": None,
            "building_age_max": None,
            "parking": None,
            "purpose": None,
            "purchase_timeline": None,
            "urgency": "HIGH",
        }
    )
    app.dependency_overrides[get_ai_service] = lambda: AIService(
        FakeLLMProvider(parsing_json)
    )

    lead = _create_lead(advice_client)
    advice_client.post(f"{PREFIX}/leads/{lead['id']}/analyze")
    _suggest(advice_client, lead["id"])

    detail = advice_client.get(f"{PREFIX}/leads/{lead['id']}").json()

    assert detail["latest_analysis"]["parsed_result"]["location"] == "七期"
    assert detail["latest_follow_up"]["parsed_result"]["next_action"]


# ---------------------------------------------------------------- 失敗情境


def test_llm_failure_returns_503_and_leaves_the_lead_alone(client, fake_llm):
    """AI 掛掉不能讓 CRM 跟著壞。"""
    fake_llm.error = LLMError("模型暫時不可用")
    app.dependency_overrides[get_follow_up_advisor] = lambda: FollowUpAdvisor(fake_llm)
    lead = _create_lead(client)

    resp = _suggest(client, lead["id"])
    assert resp.status_code == 503

    # 客戶資料照常讀得到
    assert client.get(f"{PREFIX}/leads/{lead['id']}").status_code == 200


def test_malformed_output_is_rejected(advice_client, fake_llm):
    """空字串的 next_action 通不過 Pydantic，不能存進資料庫。

    strict schema 保證「有這個欄位」，但保證不了「裡面有東西」。
    一則空白的建議顯示在畫面上，業務會以為系統壞了。
    """
    fake_llm.content = _suggestion_json(next_action="")
    lead = _create_lead(advice_client)

    assert _suggest(advice_client, lead["id"]).status_code == 503


def test_lead_without_any_information_is_rejected(advice_client):
    """既沒有原話也沒有互動紀錄時回 422，而不是讓模型去猜。"""
    lead = _create_lead(advice_client, raw_requirement=None)

    resp = _suggest(advice_client, lead["id"])
    assert resp.status_code == 422
    assert "互動紀錄" in resp.json()["detail"]


def test_lead_with_only_interactions_is_allowed(advice_client):
    """沒有原話但有互動紀錄，仍然可以給建議 ——
    電話進來的客戶常常就是這樣，需求全記在互動裡。"""
    lead = _create_lead(advice_client, raw_requirement=None)
    _add_interaction(advice_client, lead["id"], "客戶來電問七期的物件")

    assert _suggest(advice_client, lead["id"]).status_code == 200


def test_ai_not_configured_returns_503(client):
    """沒設 OPENAI_API_KEY 的環境，這顆按鈕回 503，其餘功能不受影響。"""
    app.dependency_overrides[get_follow_up_advisor] = lambda: None
    lead = _create_lead(client)

    assert _suggest(client, lead["id"]).status_code == 503


def test_cannot_suggest_for_someone_elses_lead(advice_client, other_client):
    """別人的客戶一律 404，不是 403 —— 403 等於承認這個 id 存在。"""
    lead = _create_lead(advice_client)

    assert _suggest(other_client, lead["id"]).status_code == 404


def test_every_prompt_version_has_different_content():
    """每個版號的內容必須真的不一樣。

    新版是用 .replace() 從舊版疊出來的，而 .replace() 錨點對不上時
    **不報錯，只是原封不動回傳**。這件事真的發生過：v4 的錨點少算一個換行，
    結果 v4 的內容跟 v3 一模一樣，但版號、日誌、資料庫紀錄全都顯示是 v4。

    最糟的地方在於評估還是跑得完、報告還是產得出來——
    你以為在比較兩個版本，其實在比較同一個版本兩次。
    """
    from app.services.follow_up_advisor import FOLLOW_UP_PROMPTS

    contents = list(FOLLOW_UP_PROMPTS.values())
    assert len(set(contents)) == len(contents)


def test_unknown_prompt_version_is_rejected_at_construction(fake_llm):
    """打錯版號要當場爆掉，而不是安靜地用預設版本跑完整份評估。"""
    with pytest.raises(ValueError):
        FollowUpAdvisor(fake_llm, prompt_version="follow_up_v99")
