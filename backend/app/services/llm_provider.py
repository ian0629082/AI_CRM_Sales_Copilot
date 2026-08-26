"""LLM 的最底層封裝：把字串送出去，把字串拿回來。

這一層刻意做得很薄，而且**完全不知道什麼是 Lead、什麼是房仲**。
它只認識「system prompt、user prompt、要求輸出的 JSON Schema」這三樣東西。

這樣切的兩個好處：

1. **測試不必花錢**：測試時把它換成 FakeLLMProvider 回傳固定 JSON，
   驗的是「我們的驗證與寫入邏輯對不對」。至於「AI 準不準」，
   那是 Sprint 4 Evaluation 的職責，用另一套機制量。
2. **換供應商只改這個檔案**：日後要換成 Anthropic 或地端模型，
   AIService 一行都不用動。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from openai import APIError, APITimeoutError, OpenAI

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """呼叫模型失敗。

    刻意不用 app.core.exceptions 裡的錯誤：那些帶著 HTTP 狀態碼，
    而這一層根本不該知道自己被誰呼叫、更不該知道有 HTTP 這回事。
    翻譯成 HTTP 錯誤是 AIService 的工作。
    """


@dataclass(frozen=True)
class LLMResponse:
    """模型的回應。token 數留著給 Sprint 4 算成本用。"""

    content: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class LLMProvider(Protocol):
    """所有 LLM 供應商都要長這樣。

    用 Protocol 而不是抽象基底類別（ABC）：測試用的假 provider
    不需要繼承任何東西，只要方法簽名對得上就能替換。
    """

    @property
    def model_name(self) -> str: ...

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema_name: str,
        json_schema: dict[str, Any],
    ) -> LLMResponse:
        """要求模型依照 json_schema 回傳 JSON 字串。"""
        ...


class OpenAIProvider:
    """OpenAI 的實作。"""

    def __init__(self, api_key: str, model: str, timeout: float = 30.0):
        if not api_key:
            raise LLMError("尚未設定 OPENAI_API_KEY")
        # 一定要設 timeout：這支 API 是同步等待的，
        # OpenAI 那頭卡住時會連帶把後端的工作執行緒一起佔住。
        self._client = OpenAI(api_key=api_key, timeout=timeout)
        self._model = model

    @property
    def model_name(self) -> str:
        return self._model

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema_name: str,
        json_schema: dict[str, Any],
    ) -> LLMResponse:
        try:
            completion = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        # strict 是關鍵。它跟「在 prompt 裡拜託 AI 回 JSON」
                        # 是兩種可靠度等級：strict 在解碼階段就限制模型
                        # 只能吐出符合 schema 的 token，而不是事後祈禱它有照做。
                        "name": schema_name,
                        "strict": True,
                        "schema": json_schema,
                    },
                },
            )
        except APITimeoutError as exc:
            raise LLMError(f"呼叫 {self._model} 逾時") from exc
        except APIError as exc:
            raise LLMError(f"呼叫 {self._model} 失敗：{exc}") from exc

        content = completion.choices[0].message.content
        if not content:
            # strict 模式下仍可能因為觸發長度上限或安全機制而回空值
            raise LLMError("模型沒有回傳內容")

        usage = completion.usage
        return LLMResponse(
            content=content,
            model=completion.model,
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
        )
