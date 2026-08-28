"""把手填的文字表轉成評估用的 JSON。

用法（在 backend 目錄下）：

    python -m scripts.build_holdout

讀 evaluation/holdout_form.txt，寫出 evaluation/followup_holdout.json。

---

為什麼要有這支程式：**JSON 不該讓人手寫。**

驗證集必須由具房仲實務經驗的人出題，而那個人不必也不該去記
「屋齡上限的鍵叫 building_age_max」「自住要寫 SELF_USE」。
每一個要記的規則都是一個填錯的機會，而填錯的成本是整份資料集不能用。

所以格式的複雜度留在這裡，出題的人只要用中文回答問題。

轉檔前會先驗一輪，有問題就整份不產出並印出哪一位、哪一行有問題 ——
產出一份「大致上可用」的資料集是最糟的結果：
它跑得完、會給出數字，而那些數字是錯的。
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
from datetime import date

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
FORM_PATH = BACKEND_DIR / "evaluation" / "holdout_form.txt"
OUTPUT_PATH = BACKEND_DIR / "evaluation" / "followup_holdout.json"

# 表格裡的中文答案，對應到程式裡的值。
# 收得寬一點（「已聯絡」跟「聯絡過」都認），因為填表的人不會照抄選項。
STATUS = {
    "新進": "NEW",
    "已聯絡": "CONTACTED",
    "聯絡過": "CONTACTED",
    "有興趣": "INTERESTED",
    # 「帶看」這一格是出題的人補上的：他填五筆驗證集情境，
    # 兩筆的狀態直接寫了「帶看」，而當時的漏斗根本沒有這一格。
    "帶看": "VIEWING",
    "約訪": "MEETING",
    "面談": "MEETING",
    # 買方這一端叫「斡旋」：客戶下了斡旋金，等仲介去跟屋主談。
    # 「議價」是殺價，那是對屋主做的事，買方 CRM 不會用到這個詞 ——
    # 資料庫裡的值仍然是 NEGOTIATING（改 enum 要動 migration，
    # 而這是用詞問題不是資料問題），但畫面與表格一律講斡旋。
    "斡旋": "NEGOTIATING",
    "議價": "NEGOTIATING",
    "成交": "WON",
    "流失": "LOST",
}

PROPERTY_TYPE = {
    "電梯大樓": "ELEVATOR_BUILDING",
    "大樓": "ELEVATOR_BUILDING",
    "華廈": "LOW_RISE",
    "公寓": "APARTMENT",
    "透天厝": "TOWNHOUSE",
    "透天": "TOWNHOUSE",
    "別墅": "VILLA",
    "套房": "STUDIO",
}

PURPOSE = {"自住": "SELF_USE", "投資": "INVESTMENT", "兩者": "BOTH", "都有": "BOTH"}

URGENCY = {"急": "HIGH", "很急": "HIGH", "不急": "LOW"}

# 「不要」「不用」「不需要」要排在「要」前面比對。
# pick() 是用「這個詞有沒有出現在文字裡」判斷的，
# 「不要」裡面就含著「要」—— 順序寫反的話，客戶說不用車位會變成要車位，
# 而那筆客戶的建議就會整段建立在錯的前提上。
PARKING = {
    "不要": False,
    "不用": False,
    "不需要": False,
    "沒有": False,
    "要": True,
    "需要": True,
    "有": True,
}

INTERACTION_TYPE = {
    "電話": "CALL",
    "來電": "CALL",
    "致電": "CALL",
    "LINE": "LINE",
    "line": "LINE",
    "簡訊": "LINE",
    "EMAIL": "EMAIL",
    "email": "EMAIL",
    "信": "EMAIL",
    "面談": "MEETING",
    "見面": "MEETING",
    "帶看": "VIEWING",
    "看屋": "VIEWING",
    "備註": "NOTE",
    "筆記": "NOTE",
}


class FormError(Exception):
    """填表的內容有問題。訊息要講得出「哪一位、哪一行、該怎麼改」。"""


# 表格最上面那行「今天：2026-08-27」。
#
# 為什麼需要一個基準日：評估跑起來時的「今天」是固定的
# （見 evaluate_followup.EVAL_TODAY），這樣同一份資料集在不同日子跑
# 才會得到可以互相比較的結果。
#
# 所以表格裡寫的日期要換算成「距離今天幾天」。
# 換算由程式做，填表的人照常寫日期就好 ——
# 他在 CRM 裡看到的是日期，腦子裡想的也是日期，不是「幾天前」。
TODAY_LINE = re.compile(r"^今天[：:]\s*(\S+)")

_DATE_PATTERNS = (
    (re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$"), True),  # 2026-08-25
    (re.compile(r"^(\d{1,2})[-/.](\d{1,2})$"), False),  # 8/25
)


def parse_date(text: str, anchor: date, *, prefer_past: bool = False) -> date | None:
    """把「2026-08-25」或「8/25」換成日期。看不出是日期就回 None。

    只寫月日時年份取基準日的年。`prefer_past` 決定跨年怎麼猜：

    - 過去的欄位（互動紀錄、建檔日期）要 prefer_past=True：
      一月時寫「12/28 打的電話」，指的是去年十二月。
    - 未來的欄位（下次提醒、已約帶看）不能開：
      基準日 8/27 寫「8/30 要帶看」，那是三天後，不是去年八月。

    這兩種欄位用同一條規則的話，其中一種一定會錯 ——
    而錯的方式是資料悄悄差了一整年，程式不會有任何抱怨。
    """
    text = text.strip()
    for pattern, has_year in _DATE_PATTERNS:
        match = pattern.match(text)
        if not match:
            continue
        if has_year:
            year, month, day = (int(g) for g in match.groups())
        else:
            month, day = (int(g) for g in match.groups())
            year = anchor.year
        try:
            parsed = date(year, month, day)
        except ValueError as exc:
            raise FormError(f"日期看不懂：「{text}」") from exc
        # 只有「明顯不可能是今年」時才往前推一年。
        #
        # 一開始寫成「只要比基準日晚就推去年」，結果打錯字的日期
        # （基準日 8/27，互動紀錄寫成 9/5）被悄悄變成 2025-09-05，
        # 也就是「356 天前」—— 資料差了整整一年，而程式一句話都沒說。
        #
        # 現在只有超過 90 天才推：一月寫 12/28 確實是去年，
        # 而差幾天的未來日期會留在原地，讓上層擋下來報錯。
        if prefer_past and not has_year and (parsed - anchor).days > 90:
            parsed = date(year - 1, month, day)
        return parsed
    return None


def parse_days_ago(text: str, anchor: date) -> int | None:
    """「3天前」或「8/25」→ 距離基準日幾天前。"""
    text = text.strip()
    if not text:
        return None

    parsed = parse_date(text, anchor, prefer_past=True)
    if parsed is not None:
        return (anchor - parsed).days

    match = re.match(r"^(\d+)\s*天前$", text)
    if match:
        return int(match.group(1))
    return None


# 「2000萬左右」跟「就是 2000 萬」在計分上差 10 分：
# 講概數的客戶通常還在觀望。Lead Score 分得出這兩種，
# 表格這邊也要分得出來，否則 holdout 的分數會整體偏高。
_APPROXIMATE_WORDS = ("左右", "上下", "大概", "差不多", "附近", "約")


def is_approximate_budget(text: str) -> bool:
    return any(word in text for word in _APPROXIMATE_WORDS)


def parse_money(text: str) -> tuple[int | None, int | None]:
    """把「1500萬」「1200萬到1500萬」換算成元。

    收中文的講法而不是逼人填 15000000 ——
    填表的人腦子裡想的是「一千五百萬」，多一次心算就多一個填錯的機會。
    """
    text = text.strip()
    if not text:
        return None, None

    # 業務講預算的方式，程式要跟著他走。
    # 「4000萬內」「不超過4000萬」「頂多4000萬」都是「上限4000萬」，
    # 逼人改成「4000萬」只是要他配合程式的想法。
    text = re.sub(r"^(不超過|頂多|最多|上限)\s*", "", text)
    text = re.sub(r"\s*(以內|以下|內|上限|左右|上下|大概|差不多|附近)$", "", text).strip()

    parts = re.split(r"到|~|-|～", text)

    def one(part: str) -> int:
        part = part.strip()
        match = re.match(r"^(\d+(?:\.\d+)?)\s*(萬|億)?\s*(?:元)?$", part)
        if not match:
            raise FormError(f"預算看不懂：「{part}」。請寫成 1500萬 或 15000000")
        value = float(match.group(1))
        unit = match.group(2)
        if unit == "萬":
            value *= 10_000
        elif unit == "億":
            value *= 100_000_000
        return int(value)

    if len(parts) == 2 and parts[1].strip():
        low, high = one(parts[0]), one(parts[1])
        if low > high:
            raise FormError(f"預算的下限比上限大：「{text}」")
        return low, high
    return None, one(parts[0])


# 「沒有限制」的各種講法。
#
# 這些要當成「沒填」，不是當成錯誤。填表的人寫「不限」是在明確回答
# 「這一項客戶沒有要求」—— 逼他改成留空，只是要他配合程式的想法。
NO_LIMIT = ("不限", "不拘", "無", "沒有", "都可以", "都行", "沒差", "隨便")


def parse_int(text: str, label: str) -> int | None:
    text = text.strip()
    if not text or any(word in text for word in NO_LIMIT):
        return None
    match = re.search(r"-?\d+", text)
    if not match:
        raise FormError(f"{label} 要填數字，現在填的是：「{text}」")
    return int(match.group(0))


def pick(table: dict, text: str, label: str):
    """把中文答案換成程式裡的值。填的字不在表上就報錯，不要猜。"""
    text = text.strip().strip("（）()")
    if not text:
        return None
    for key, value in table.items():
        if key in text:
            return value
    raise FormError(f"{label} 看不懂：「{text}」。可以填：{'／'.join(table)}")


def parse_viewing(text: str, anchor: date) -> tuple[int, int] | None:
    """「8/28 15:00」或「1 15」→ (距今幾天, 幾點)。"""
    text = text.strip()
    if not text:
        return None

    parts = text.split()
    # 先試日期寫法：「8/28 15:00」「2026-08-28 下午3點」
    if len(parts) >= 2:
        parsed = parse_date(parts[0], anchor)
        if parsed is not None:
            hour_text = " ".join(parts[1:])
            hour_match = re.search(r"(\d{1,2})", hour_text)
            if not hour_match:
                raise FormError(f"帶看時間看不懂幾點：「{hour_text}」，例如 15:00")
            hour = int(hour_match.group(1))
            _check_hour(hour)
            return (parsed - anchor).days, hour

    numbers = re.findall(r"\d+", text)
    if len(numbers) < 2:
        raise FormError(
            f"已約帶看看不懂：「{text}」\n"
            "  可以寫日期加時間，例如  8/28 15:00\n"
            "  或寫「幾天後 幾點」，例如  1 15  （明天下午三點）"
        )
    day, hour = int(numbers[0]), int(numbers[1])
    _check_hour(hour)
    return day, hour


def _check_hour(hour: int) -> None:
    if not 0 <= hour <= 23:
        raise FormError(f"帶看時間的「幾點」要在 0～23 之間，現在是 {hour}")


def parse_interaction(line: str, anchor: date) -> dict:
    """「8/25 電話 客戶說他還在考慮」→ 一筆互動紀錄。

    日期跟「3天前」兩種寫法都收。
    業務在 CRM 裡看到的是日期，腦子裡想的也是日期 ——
    逼他自己換算成「幾天前」，是拿程式的方便去換他的麻煩，
    而且換算錯了不會有人發現。
    """
    match = re.match(r"^\s*(\S+)\s+(\S+)\s+(.+)$", line)
    if not match:
        raise FormError(
            f"互動紀錄這一行看不懂：「{line.strip()}」\n"
            "  格式是：日期 + 管道 + 內容，例如\n"
            "  8/25 電話 客戶說他還在考慮，叫我下週再打給他"
        )
    when, channel, content = match.groups()

    days_ago = parse_days_ago(when, anchor)
    if days_ago is None:
        raise FormError(
            f"互動紀錄的日期看不懂：「{when}」（這一行：{line.strip()}）\n"
            "  可以寫  8/25  或  2026-08-25  或  3天前"
        )
    if days_ago < 0:
        # 最常見的原因其實是**基準日忘了改**：表單放了幾天才填完，
        # 今天記的互動就會落在基準日之後。
        # 第一版的訊息只講了「還沒發生的帶看請填在已約帶看」，
        # 把人導向去改互動紀錄 —— 而那一行其實是對的，要改的是最上面那行。
        raise FormError(
            # 不用 strftime：%-m 在 Windows 上是無效的格式碼，會直接丟例外，
            # 而這裡本來就是在報錯，再爆一次會把真正的原因蓋掉。
            f"互動紀錄的日期「{when}」比基準日（{anchor.month}/{anchor.day}）還晚。\n"
            "  兩種可能：\n"
            f"  1. 這筆互動就是今天發生的 → 把表格最上面的「今天：」改成今天的日期\n"
            "  2. 這件事還沒發生 → 還沒去的帶看要填在「已約帶看」那一欄"
        )

    kind = pick(INTERACTION_TYPE, channel, "互動管道")
    return {"type": kind, "days_ago": days_ago, "content": content.strip()}


def split_blocks(raw: str) -> list[tuple[str, list[str]]]:
    """把整份表切成一位客戶一段。"""
    blocks: list[tuple[str, list[str]]] = []
    current_title: str | None = None
    current: list[str] = []

    for line in raw.splitlines():
        stripped = line.strip()
        # 只有「=== 第 N 位 ===」算區塊開頭。
        # 純粹由等號組成的分隔線是排版用的，不能當成新的一位客戶 ——
        # 否則說明文字會被當成某一位的欄位，然後報出一堆莫名其妙的錯。
        is_separator = stripped.startswith("===") and not stripped.strip("= ")
        if stripped.startswith("===") and not is_separator:
            if current_title is not None:
                blocks.append((current_title, current))
            current_title = stripped.strip("= ")
            current = []
        elif current_title is not None:
            current.append(line)

    if current_title is not None:
        blocks.append((current_title, current))
    return blocks


def parse_block(
    title: str, lines: list[str], index: int, anchor: date | None = None
) -> dict | None:
    """一位客戶。整段都沒填就回 None（表格裡沒用到的空位）。"""
    anchor = anchor or date.today()
    fields: dict[str, str] = {}
    interactions: list[dict] = []
    in_interactions = False

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("---"):
            if stripped.startswith("--- 這一位結束"):
                in_interactions = False
            continue

        if stripped.startswith("互動紀錄"):
            in_interactions = True
            # 「互動紀錄」後面如果還有字，那是有人把內容直接寫在標題行上。
            #
            # 這件事真的發生了：有人寫「互動紀錄 已聯繫上，詢問需求後會再連絡」，
            # 而原本的程式只是把整行當成標題跳過 —— 那筆紀錄就這樣**靜默消失**。
            #
            # 靜默丟資料是這支程式最不能犯的錯：他以為自己出了一題有互動歷史的，
            # 實際上跑的是一題沒有歷史的，而報告上不會有任何跡象。
            # 寧可在這裡擋下來要他改，也不要讓他拿到一份悄悄少了東西的資料集。
            leftover = re.sub(r"^互動紀錄", "", stripped)
            leftover = re.sub(r"^（.*?）", "", leftover.strip()).strip()
            if leftover:
                raise FormError(
                    f"「互動紀錄」這四個字後面不要直接寫內容：「{leftover}」\n"
                    "  請換到下一行，並且加上日期和管道，例如\n"
                    "  8/25 電話 已聯繫上，問完需求，有適合的案件再跟他連絡"
                )
            continue

        # 用全形括號整行包起來的是範本裡的說明，跳過。
        # 留著讓填表的人有例子可以照抄，刪不刪都不影響結果 ——
        # 「照抄一行然後改掉內容」比「看著空白想格式」容易得多。
        if stripped.startswith("（") and stripped.endswith("）"):
            continue

        if in_interactions:
            interactions.append(parse_interaction(stripped, anchor))
            continue

        if "：" in stripped or ":" in stripped:
            key, _, value = stripped.replace(":", "：").partition("：")
            # 把還沒填的欄位後面那串括號提示去掉
            value = re.sub(r"^（.*?）$", "", value.strip()).strip()
            fields[key.strip()] = value

    name = fields.get("姓名", "").strip()
    if not name:
        # 整段都沒填 —— 那是表格裡沒用到的空位，跳過就好，不是錯誤
        if not any(fields.values()) and not interactions:
            return None
        raise FormError("有填其他欄位但沒填姓名")

    budget_text = fields.get("預算", "")
    budget_min, budget_max = parse_money(budget_text)

    lead: dict = {
        "name": name,
        "status": pick(STATUS, fields.get("狀態", ""), "狀態") or "NEW",
    }
    optional = {
        "phone": fields.get("電話", "").strip(),
        "raw_requirement": fields.get("客戶原話", "").strip(),
        "location": fields.get("區域", "").strip(),
        "budget_min": budget_min,
        "budget_max": budget_max,
        "rooms": parse_int(fields.get("房數", ""), "房數"),
        "property_type": pick(PROPERTY_TYPE, fields.get("房屋類型", ""), "房屋類型"),
        "building_age_max": parse_int(fields.get("屋齡上限", ""), "屋齡上限"),
        "parking": pick(PARKING, fields.get("車位", ""), "車位"),
        "purpose": pick(PURPOSE, fields.get("目的", ""), "目的"),
        "urgency": pick(URGENCY, fields.get("急迫", ""), "急迫"),
    }
    # 沒填的欄位整個不放進去，而不是填 null。
    # 「客戶沒提到」在計分上跟「沒有這個鍵」是同一件事，少一堆 null 也好讀得多。
    lead.update({k: v for k, v in optional.items() if v not in (None, "")})

    if budget_max is not None and is_approximate_budget(budget_text):
        lead["budget_is_approximate"] = True

    # 建檔日期收兩種寫法。「建檔幾天了」是舊版表格的欄位，
    # 已經填過的人不該因為表格改版就得重填。
    created = fields.get("建檔日期", "").strip()
    if created:
        days_since = parse_days_ago(created, anchor)
        if days_since is None:
            raise FormError(f"建檔日期看不懂：「{created}」，可以寫 8/25 或 2026-08-25")
    else:
        days_since = parse_int(fields.get("建檔幾天了", ""), "建檔幾天了")

    case: dict = {
        "id": f"hold-{index:03d}",
        "tags": [],
        "days_since_created": days_since if days_since is not None else 1,
        "lead": lead,
        "interactions": interactions,
    }

    # 下次提醒：日期，或「幾天後」（負數代表已經逾期）。
    reminder_text = fields.get("下次提醒", "").strip()
    if reminder_text:
        reminder_date = parse_date(reminder_text, anchor)
        if reminder_date is not None:
            case["next_follow_up_in_days"] = (reminder_date - anchor).days
        else:
            reminder = parse_int(reminder_text, "下次提醒")
            if reminder is not None:
                case["next_follow_up_in_days"] = reminder

    viewing = parse_viewing(fields.get("已約帶看", ""), anchor)
    if viewing is not None:
        case["viewing_in_days"], case["viewing_hour"] = viewing

    return case


def main() -> int:
    if not FORM_PATH.exists():
        print(f"找不到 {FORM_PATH}", file=sys.stderr)
        return 1

    raw = FORM_PATH.read_text(encoding="utf-8")

    # 表格最上面的「今天：2026-08-27」。沒寫就用真正的今天。
    anchor = date.today()
    for line in raw.splitlines():
        match = TODAY_LINE.match(line.strip())
        if match:
            parsed = parse_date(match.group(1), date.today())
            if parsed is None:
                print(
                    f"最上面那行的「今天」看不懂：「{match.group(1)}」，"
                    "請寫成 2026-08-27",
                    file=sys.stderr,
                )
                return 1
            anchor = parsed
            break

    blocks = split_blocks(raw)
    cases: list[dict] = []
    errors: list[str] = []

    for title, lines in blocks:
        try:
            case = parse_block(title, lines, len(cases) + 1, anchor)
        except FormError as exc:
            errors.append(f"【{title}】{exc}")
            continue
        if case is not None:
            cases.append(case)

    if errors:
        # 有錯就整份不產出。
        # 產一份「大致上可用」的資料集是最糟的結果：它跑得完、會給數字，而數字是錯的。
        print("表格裡有幾個地方要修：\n", file=sys.stderr)
        for error in errors:
            print(f"  {error}\n", file=sys.stderr)
        print("改好之後再執行一次。", file=sys.stderr)
        return 1

    if not cases:
        print(
            f"{FORM_PATH.name} 還是空的。\n"
            "請先填幾位客戶的情境，再執行這支程式。",
            file=sys.stderr,
        )
        return 1

    payload = {
        "meta": {
            "version": "v1",
            "case_count": len(cases),
            "purpose": "跟進建議的 held-out 驗證集",
            "source": "由具房仲業務實務經驗、且未讀過 prompt 的人出題",
            "generated_from": FORM_PATH.name,
            # 表格裡寫的是日期，這裡存下當時的基準日，
            # 日後要對照「這一筆的互動到底是哪一天」才查得回去。
            "form_today": anchor.isoformat(),
            "how_to_read": [
                "這份**只用來量測，永遠不拿來調 prompt**。",
                "它的全部價值來自「從沒影響過任何決定」——",
                "看著它的失敗改一次 prompt，它就往開發集靠一步。",
                "",
                "不要手動編輯這個檔案，改 holdout_form.txt 之後重新產生。",
            ],
        },
        "cases": cases,
    }
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    with_viewing = sum(1 for c in cases if "viewing_in_days" in c)
    with_history = sum(1 for c in cases if c["interactions"])
    print(f"✅ 產生了 {len(cases)} 筆情境 → {OUTPUT_PATH.name}")
    print(f"   有互動紀錄的 {with_history} 筆、有帶看約的 {with_viewing} 筆")
    print()
    print("接著就可以跑：")
    print("   python -m scripts.evaluate_followup --dataset holdout --judge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
