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
    "面談": "MEETING",
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

PARKING = {"要": True, "需要": True, "不要": False, "不需要": False}

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


def parse_money(text: str) -> tuple[int | None, int | None]:
    """把「1500萬」「1200萬到1500萬」換算成元。

    收中文的講法而不是逼人填 15000000 ——
    填表的人腦子裡想的是「一千五百萬」，多一次心算就多一個填錯的機會。
    """
    text = text.strip()
    if not text:
        return None, None

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


def parse_int(text: str, label: str) -> int | None:
    text = text.strip()
    if not text:
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


def parse_viewing(text: str) -> tuple[int, int] | None:
    """「1 15」→ 明天 15 點。"""
    text = text.strip()
    if not text:
        return None
    numbers = re.findall(r"\d+", text)
    if len(numbers) < 2:
        raise FormError(
            f"已約帶看要填兩個數字（幾天後、幾點），現在填的是：「{text}」。"
            "例如「1 15」代表明天下午三點"
        )
    day, hour = int(numbers[0]), int(numbers[1])
    if not 0 <= hour <= 23:
        raise FormError(f"帶看時間的「幾點」要在 0～23 之間，現在是 {hour}")
    return day, hour


def parse_interaction(line: str) -> dict:
    """「3天前 電話 客戶說他還在考慮」→ 一筆互動紀錄。"""
    match = re.match(r"^\s*(\d+)\s*天前\s+(\S+)\s+(.+)$", line)
    if not match:
        raise FormError(
            f"互動紀錄這一行看不懂：「{line.strip()}」\n"
            "  格式是：幾天前 + 管道 + 內容，例如\n"
            "  3天前 電話 客戶說他還在考慮，叫我下週再打給他"
        )
    days_ago, channel, content = match.groups()
    kind = pick(INTERACTION_TYPE, channel, "互動管道")
    return {"type": kind, "days_ago": int(days_ago), "content": content.strip()}


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


def parse_block(title: str, lines: list[str], index: int) -> dict | None:
    """一位客戶。整段都沒填就回 None（表格裡沒用到的空位）。"""
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
            continue

        # 用全形括號整行包起來的是範本裡的說明，跳過。
        # 留著讓填表的人有例子可以照抄，刪不刪都不影響結果 ——
        # 「照抄一行然後改掉內容」比「看著空白想格式」容易得多。
        if stripped.startswith("（") and stripped.endswith("）"):
            continue

        if in_interactions:
            interactions.append(parse_interaction(stripped))
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

    budget_min, budget_max = parse_money(fields.get("預算", ""))

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

    case: dict = {
        "id": f"hold-{index:03d}",
        "tags": [],
        "days_since_created": parse_int(fields.get("建檔幾天了", ""), "建檔幾天了") or 1,
        "lead": lead,
        "interactions": interactions,
    }

    reminder = parse_int(fields.get("下次提醒", ""), "下次提醒")
    if reminder is not None:
        case["next_follow_up_in_days"] = reminder

    viewing = parse_viewing(fields.get("已約帶看", ""))
    if viewing is not None:
        case["viewing_in_days"], case["viewing_hour"] = viewing

    return case


def main() -> int:
    if not FORM_PATH.exists():
        print(f"找不到 {FORM_PATH}", file=sys.stderr)
        return 1

    blocks = split_blocks(FORM_PATH.read_text(encoding="utf-8"))
    cases: list[dict] = []
    errors: list[str] = []

    for title, lines in blocks:
        try:
            case = parse_block(title, lines, len(cases) + 1)
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
