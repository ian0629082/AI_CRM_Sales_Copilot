"""跟進建議的每日次數上限（Sprint 7）。

這個上限防的不是攻擊，是「按著玩」與「按了沒反應就一直按」——
每一次都是真的付錢給 OpenAI。

這種省錢用的機制最容易寫完就以為它在跑，所以這裡守四件事：

1. 到達上限之後真的擋得下來
2. **擋下來的時候沒有呼叫模型**（擋在花錢之後就毫無意義了）
3. 額度是各人各自的，別人用掉的不算在我頭上
4. 昨天用掉的不算今天的

第 2 條是這一份的重點。只驗「回 429」的話，一個先呼叫模型再回 429 的
實作也會過測試 —— 那正是這個功能唯一要避免的事。
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.clock import local_day_start_utc
from app.core.config import settings
from app.models.ai_analysis import FOLLOW_UP, AIAnalysis

from tests.test_follow_up_advice import (  # noqa: F401  fixture 一起帶進來
    PREFIX,
    FakeLLMProvider,
    _create_lead,
    _suggest,
    advice_client,
    fake_llm,
)


@pytest.fixture
def limit_of_two(monkeypatch: pytest.MonkeyPatch) -> int:
    """把上限調成 2，測試才不必按十次。

    上限本身是設定值不是常數，正是為了這種可調整性 ——
    Demo 期間想放寬也不必改程式碼。
    """
    monkeypatch.setattr(settings, "FOLLOW_UP_DAILY_LIMIT", 2)
    return 2


def test_blocks_after_reaching_limit(advice_client, limit_of_two):
    lead = _create_lead(advice_client)

    for i in range(limit_of_two):
        assert _suggest(advice_client, lead["id"]).status_code == 200, f"第 {i + 1} 次"

    resp = _suggest(advice_client, lead["id"])
    assert resp.status_code == 429


def test_limit_message_says_when_it_resets(advice_client, limit_of_two):
    """訊息要講清楚上限是多少、什麼時候恢復。

    只說「已達上限」的話，使用者不知道該等一分鐘還是等到明天 ——
    那種不確定比限制本身更難受，而且他會一直按下去確認。
    """
    lead = _create_lead(advice_client)
    for _ in range(limit_of_two):
        _suggest(advice_client, lead["id"])

    detail = _suggest(advice_client, lead["id"]).json()["detail"]
    assert str(limit_of_two) in detail
    assert "明天" in detail


def test_does_not_call_the_model_when_blocked(
    advice_client, fake_llm: FakeLLMProvider, limit_of_two
):
    """被擋下來的那一次不能呼叫模型。

    這是整個機制的重點：擋在花錢之後等於沒擋。
    """
    lead = _create_lead(advice_client)
    for _ in range(limit_of_two):
        _suggest(advice_client, lead["id"])

    calls_before = len(fake_llm.calls)
    _suggest(advice_client, lead["id"])

    assert len(fake_llm.calls) == calls_before


def test_limit_is_per_user(advice_client, other_client: TestClient, limit_of_two):
    """額度各人各自算。

    用同一張 ai_analysis 表計數時，這一條特別容易寫錯 ——
    少了 owner 的過濾條件，團隊裡最勤勞的那個人會把所有人的額度用光，
    而其他人只會看到「今天已經用完」，完全不知道發生什麼事。
    """
    my_lead = _create_lead(advice_client)
    for _ in range(limit_of_two):
        _suggest(advice_client, my_lead["id"])
    assert _suggest(advice_client, my_lead["id"]).status_code == 429

    其他人的客戶 = _create_lead(other_client)
    assert _suggest(other_client, 其他人的客戶["id"]).status_code == 200


def test_yesterday_does_not_count(
    advice_client, db_session: Session, limit_of_two
):
    """昨天用掉的不佔今天的額度。

    直接把紀錄的時間改到日界線之前，比等一天可靠得多。
    """
    lead = _create_lead(advice_client)
    for _ in range(limit_of_two):
        _suggest(advice_client, lead["id"])
    assert _suggest(advice_client, lead["id"]).status_code == 429

    # 把已經產生的紀錄挪到「當地今天」的開始之前一小時。
    before_today = local_day_start_utc() - timedelta(hours=1)
    for analysis in db_session.query(AIAnalysis).filter(
        AIAnalysis.analysis_type == FOLLOW_UP
    ):
        analysis.created_at = before_today
    db_session.commit()

    assert _suggest(advice_client, lead["id"]).status_code == 200


# ---------------------------------------------------------------- 日界線


def test_local_day_start_uses_taipei_midnight():
    """日界線用台北時間算，不是 UTC。

    伺服器在 UTC，使用者在台灣。照 UTC 算的話額度會在台灣時間早上八點
    重置 —— 業務早上進辦公室按了幾次，額度就莫名其妙跳掉了。
    """
    # 台北時間 2026-09-02 07:00 = UTC 2026-09-01 23:00
    now = datetime(2026, 9, 1, 23, 0, tzinfo=UTC)

    start = local_day_start_utc(now)

    # 台北的今天是 9/2，它的 00:00 等於 UTC 的 9/1 16:00
    assert start == datetime(2026, 9, 1, 16, 0, tzinfo=UTC)


def test_local_day_start_is_before_now():
    """任何時刻的「今天開始」都不能落在未來。

    看起來理所當然，但時區換算寫反了正好會產生這種結果，
    而症狀是「額度永遠是 0」—— 一個完全不會報錯的失效。
    """
    for hour in range(24):
        now = datetime(2026, 9, 1, hour, 30, tzinfo=UTC)
        assert local_day_start_utc(now) <= now
