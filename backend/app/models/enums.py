"""系統中所有的列舉值。

集中在同一個檔案，避免 model / schema / service 各自定義一份而不同步。
"""

from enum import Enum


class LeadStatus(str, Enum):
    """Lead 在銷售漏斗中的位置（對應 Dashboard 的 Lead Funnel）。"""

    NEW = "NEW"
    CONTACTED = "CONTACTED"
    INTERESTED = "INTERESTED"
    MEETING = "MEETING"
    NEGOTIATING = "NEGOTIATING"
    WON = "WON"
    LOST = "LOST"  # 規劃書的漏斗只畫到 WON，但要算 Conversion Rate 就必須有終止狀態


class LeadLevel(str, Enum):
    """由 Lead Score 換算出的優先層級（Sprint 5 的 Scoring Engine 負責填）。"""

    HOT = "HOT"
    WARM = "WARM"
    COLD = "COLD"


class InteractionType(str, Enum):
    """業務與客戶的互動管道。"""

    CALL = "CALL"
    LINE = "LINE"
    EMAIL = "EMAIL"
    MEETING = "MEETING"
    VIEWING = "VIEWING"  # 帶看
    NOTE = "NOTE"


class LeadSource(str, Enum):
    """Lead 的來源管道。"""

    WEB_FORM = "WEB_FORM"
    PHONE = "PHONE"
    REFERRAL = "REFERRAL"
    WALK_IN = "WALK_IN"
    LINE = "LINE"
    OTHER = "OTHER"


class Purpose(str, Enum):
    """購屋目的。AI 解析自然語言後會填入這個欄位。"""

    SELF_USE = "SELF_USE"  # 自住
    INVESTMENT = "INVESTMENT"  # 投資
    BOTH = "BOTH"
    UNKNOWN = "UNKNOWN"
