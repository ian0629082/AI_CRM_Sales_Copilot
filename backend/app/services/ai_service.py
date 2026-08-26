"""AI 需求解析：決定「用什麼 prompt、怎麼驗證結果」。

分層上它夾在中間：

    LeadService   決定「要不要分析、分析完怎麼處理」
         ↓
    AIService     決定「用什麼 prompt、怎麼驗證結果」   ← 這個檔案
         ↓
    LLMProvider   只負責「把字串送給模型拿回字串」

AIService 認識房仲業務，但不認識資料庫，也不認識 HTTP。
它的輸入是一段客戶原話，輸出是一個驗證過的 ParsedRequirement。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

from pydantic import ValidationError as PydanticValidationError

from app.core.exceptions import AIServiceError
from app.models.enums import PropertyType, Purpose
from app.schemas.ai import ParsedRequirement
from app.services.llm_provider import LLMError, LLMProvider

logger = logging.getLogger(__name__)

# Prompt 一改版就進一個版號，舊版留著不刪。
#
# 留著舊版不是念舊，是為了能回答「v2 到底有沒有比 v1 準」——
# 兩個版本都能跑同一份評估資料集，數字擺在一起才有意義。
# 每次分析都會把版號存進 ai_analysis 表，日後看到一筆奇怪的解析結果，
# 也查得出它是哪一版 prompt 產生的。
PROMPT_V1 = "lead_analysis_v1"
PROMPT_V2 = "lead_analysis_v2"

DEFAULT_PROMPT_VERSION = PROMPT_V2

SYSTEM_PROMPT_V1 = """你是台灣房仲公司的資料整理助理。
你的工作是把業務記下的客戶原話，整理成結構化欄位。

最重要的兩條原則：**不推算**、**不補全**。
客戶沒說的就是沒說，一律填 null。寧可少填，也不要生出客戶從沒講過的資訊。

抽取規則：

【預算】金額一律換算成「元」（1 萬 = 10000）
- 「預算 2000 萬」→ budget_max=20000000、budget_is_approximate=false
  （房仲情境下客戶講預算，講的幾乎都是上限）
- 「1500 到 2000 萬」→ budget_min=15000000、budget_max=20000000
  （明確講出區間，才填兩端）
- 「2000 萬左右」「大概 2000 萬」→ budget_max=20000000、budget_is_approximate=true
  （不要自己推算成 1900～2100 萬這種區間）
- 沒提到預算 → budget_min、budget_max 皆為 null，budget_is_approximate=false

【房數 rooms】
- 「三房」→ 3
- 「三、四房都可以」→ 3（取下限，業務實務上先從門檻找起）

【房屋類型 property_type】只能是以下其一，沒提到就 null
- ELEVATOR_BUILDING 電梯大樓
- LOW_RISE 華廈
- APARTMENT 公寓（無電梯）
- TOWNHOUSE 透天厝
- VILLA 別墅
- STUDIO 套房

【屋齡 building_age_max】單位是年
- 「屋齡 10 年內」→ 10
- 「新成屋」「中古屋」「不要太舊」→ null（沒有數字就不要推算年數）

【購屋時程 purchase_timeline】單位是月
- 「三個月內」→ 3、「半年內」→ 6、「一年內」→ 12
- 「不急」「再看看」「明年再說」→ null（不要猜數字）

【車位 parking】
- 「要有車位」「有車位最好」→ true
- 「不用車位」→ false
- 沒提到 → null

【購屋目的 purpose】SELF_USE 自住 / INVESTMENT 投資 / BOTH 兩者皆有 / null 未提及
- 「自己住」→ SELF_USE、「收租」「置產」→ INVESTMENT
- 只寫 UNKNOWN 是多餘的，沒提到就填 null

【區域 location】保留客戶的原話
- 「七期」→ "七期"（不要自行補成「台中七期」）
- 「想找信義區」→ "信義區"
"""

# v2 的修改全部來自 v1 的 Error Analysis（見 docs/evaluation/）。
#
# v1 的 40 筆評估中，9 個錯誤裡有 7 個集中在 location：模型會把「捷運附近」
# 「學區附近」「郊區」這種條件當成區域填進去，也會把「內湖或南港」整串塞進單一欄位。
# 追究原因，是 v1 只寫了「保留客戶原話」，卻沒有定義「什麼才算區域」——
# 規則在標註標準裡有，但沒被寫進 prompt。這不是模型笨，是我們沒講清楚。
#
# 另外補上三條同樣是「規則存在但沒寫進 prompt」的：
# 時程的「這個月」、房屋類型不可由「有電梯」反推、居住用途的認定。
SYSTEM_PROMPT_V2 = """你是台灣房仲公司的資料整理助理。
你的工作是把業務記下的客戶原話，整理成結構化欄位。

最重要的兩條原則：**不推算**、**不補全**。
客戶沒說的就是沒說，一律填 null。寧可少填，也不要生出客戶從沒講過的資訊。

抽取規則：

【預算】金額一律換算成「元」（1 萬 = 10000，1 億 = 100000000）
- 「預算 2000 萬」→ budget_max=20000000、budget_is_approximate=false
  （房仲情境下客戶講預算，講的幾乎都是上限）
- 「1500 到 2000 萬」→ budget_min=15000000、budget_max=20000000
  （明確講出區間，才填兩端）
- 「2000 萬左右」「2000 萬上下」「大概 2000 萬」
  → budget_max=20000000、budget_is_approximate=true
  （不要自己推算成 1900～2100 萬這種區間）
- 「不能超過 2000 萬」「頂多 2000 萬」「2000 萬以內」
  → budget_max=20000000、budget_is_approximate=false（這是明確上限，不是概數）
- 句子裡若同時出現物件開價與客戶預算，只取客戶的預算
- 沒提到預算 → budget_min、budget_max 皆為 null，budget_is_approximate=false

【房數 rooms】
- 「三房」「三房兩廳」「三房兩衛」→ 3（廳、衛的數字不影響）
- 「三、四房都可以」「兩房以上」→ 取下限（3、2）
- 「一次買兩間」是數量不是房數 → 不要填進 rooms

【房屋類型 property_type】只能是以下其一，沒提到就 null
- ELEVATOR_BUILDING 電梯大樓（客戶說「大樓」也算）
- LOW_RISE 華廈
- APARTMENT 公寓（無電梯）
- TOWNHOUSE 透天厝
- VILLA 別墅
- STUDIO 套房
只有客戶講出上面這幾種類型時才填。
「要有電梯」不能填 ELEVATOR_BUILDING —— 電梯大樓和華廈都有電梯，無法唯一對應。
「不要公寓」是排除條件，不能反過來推成別的類型。這兩種情況都填 null。

【屋齡 building_age_max】單位是年
- 「屋齡 10 年內」「屋齡十年內」→ 10
- 「新成屋」「中古屋」「新古屋」「不要太舊」「屋齡不限」→ null
  （沒有明確數字就不要推算年數）

【購屋時程 purchase_timeline】單位是月
- 「這個月」→ 1、「三個月內」→ 3、「半年內」→ 6、「一年內」→ 12、「兩年內」→ 24
- 「不急」「再看看」「明年再說」「越快越好」「明年上半年」「農曆年前」→ null
  （沒有明確月數就不要換算，即使聽起來像有時間感）

【車位 parking】
- 「要有車位」「有車位最好」「一定要有車位」「車位要平面的」→ true
  （即使後面補了「沒有也沒關係」，只要提到需求就是 true）
- 「不用車位」「不需要車位」→ false
- 沒提到 → null

【購屋目的 purpose】SELF_USE 自住 / INVESTMENT 投資 / BOTH 兩者皆有 / null 未提及
- 「自己住」「自住」→ SELF_USE
- 客戶明確描述居住用途（例如「小孩要念書」「換屋自己住」）也算 SELF_USE
- 「收租」「置產」「投資」→ INVESTMENT
- 沒提到就填 null，不要填 UNKNOWN

【區域 location】填客戶講的地名，講法保留原樣
- 什麼才算地名：縣市、行政區、鄉鎮市、重劃區、知名地段名
  例：「信義區」「板橋」「七期」「新莊副都心」「桃園藝文特區」「板橋江子翠」
- 這些**不是**地名，一律填 null：
  「捷運附近」「學區附近」「郊區」「市中心」「交通方便的地方」「海景」
  以及建案名稱（例如「帝寶」）
- 只取地名本身，把附加的描述去掉：「淡水海景」→ "淡水"
- 客戶講了多個區域時，取他先講的那一個：「內湖或南港」→ "內湖"
- 講法保留原樣，不補全也不縮短：
  客戶說「七期」就填 "七期"，說「台中七期」就填 "台中七期"
"""

PROMPTS: dict[str, str] = {
    PROMPT_V1: SYSTEM_PROMPT_V1,
    PROMPT_V2: SYSTEM_PROMPT_V2,
}


def _nullable(*types: str) -> list[str]:
    return [*types, "null"]


# 手寫 JSON Schema 而不是從 Pydantic 自動生成：
# OpenAI 的 strict 模式對 schema 有額外要求（每個欄位都必須出現在 required、
# 不能有 default、additionalProperties 必須是 false），
# 自動生成的結果常常差一點點就被拒絕，反而更難查。寫死在這裡最清楚。
REQUIREMENT_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "location": {"type": _nullable("string")},
        "budget_min": {"type": _nullable("integer")},
        "budget_max": {"type": _nullable("integer")},
        "budget_is_approximate": {"type": "boolean"},
        "rooms": {"type": _nullable("integer")},
        "property_type": {
            "type": _nullable("string"),
            "enum": [*(t.value for t in PropertyType), None],
        },
        "building_age_max": {"type": _nullable("integer")},
        "parking": {"type": _nullable("boolean")},
        "purpose": {
            "type": _nullable("string"),
            "enum": [*(p.value for p in Purpose), None],
        },
        "purchase_timeline": {"type": _nullable("integer")},
    },
    # strict 模式要求「所有欄位都必須列在 required」。
    # 這不代表值不能是 null —— 而是模型不准偷偷少回一個欄位。
    "required": [
        "location",
        "budget_min",
        "budget_max",
        "budget_is_approximate",
        "rooms",
        "property_type",
        "building_age_max",
        "parking",
        "purchase_timeline",
        "purpose",
    ],
}


@dataclass(frozen=True)
class ParseOutcome:
    """一次解析的完整結果：抽出的需求，加上要存進 ai_analysis 的那些後設資料。"""

    requirement: ParsedRequirement
    model: str
    prompt_version: str
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int


class AIService:
    def __init__(
        self, provider: LLMProvider, prompt_version: str = DEFAULT_PROMPT_VERSION
    ):
        # provider 由外部注入，而不是在這裡 new 一個 OpenAIProvider。
        # 這一行就是整個測試策略的關鍵：測試時傳入假的 provider，
        # 不必花錢，也不會因為模型的隨機性而時紅時綠。
        self.provider = provider

        if prompt_version not in PROMPTS:
            raise ValueError(f"未知的 prompt 版本：{prompt_version}")
        self.prompt_version = prompt_version

    def parse_requirement(self, raw_requirement: str) -> ParseOutcome:
        started = time.perf_counter()

        try:
            response = self.provider.complete_json(
                system_prompt=PROMPTS[self.prompt_version],
                user_prompt=f"客戶原話：\n{raw_requirement}",
                schema_name="lead_requirement",
                json_schema=REQUIREMENT_JSON_SCHEMA,
            )
        except LLMError as exc:
            # 在這裡把「模型層的錯」翻譯成「應用層的錯」。
            # 上層只需要知道「AI 這次不能用」，不必認識 OpenAI 的錯誤型別。
            logger.warning("LLM 呼叫失敗：%s", exc)
            raise AIServiceError() from exc

        latency_ms = int((time.perf_counter() - started) * 1000)

        try:
            payload = json.loads(response.content)
            requirement = ParsedRequirement.model_validate(payload)
        except (json.JSONDecodeError, PydanticValidationError) as exc:
            # strict schema 已經保證結構正確，走到這裡多半是數值不合理
            # （預算多打了幾個零、屋齡 500 年）。擋下來，不要寫進資料庫。
            logger.warning(
                "AI 回傳的內容未通過驗證：%s | 原始內容=%s", exc, response.content
            )
            raise AIServiceError("AI 回傳的內容不符合預期格式，請再試一次") from exc

        logger.info(
            "需求解析完成 model=%s prompt_version=%s latency=%sms tokens=%s/%s",
            response.model,
            self.prompt_version,
            latency_ms,
            response.prompt_tokens,
            response.completion_tokens,
        )

        return ParseOutcome(
            requirement=requirement,
            model=response.model,
            prompt_version=self.prompt_version,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            latency_ms=latency_ms,
        )
