"""系統中所有的列舉值。

集中在同一個檔案，避免 model / schema / service 各自定義一份而不同步。
"""

from enum import Enum


class LeadStatus(str, Enum):
    """Lead 在銷售漏斗中的位置（對應 Dashboard 的 Lead Funnel）。"""

    NEW = "NEW"
    CONTACTED = "CONTACTED"
    INTERESTED = "INTERESTED"
    # 約好要碰面／拿資料過去，但還沒去。畫面上顯示「約訪」。
    #
    # 值仍然叫 MEETING（改值要動 migration，而這是用詞問題不是資料問題），
    # 但業務實務上講的是「約訪」——「面談」聽起來像已經見過面了。
    MEETING = "MEETING"
    # 帶看。這是房仲買方流程最核心的一個里程碑。
    #
    # 這一格是**出題的人自己補上的**：他填五筆驗證集情境，
    # 兩筆的狀態直接寫了「帶看」，而當時的漏斗根本沒有這一格。
    # 原本的漏斗是照規劃書設計的，不是照真實流程設計的。
    #
    # 為什麼它重要：帶看是「客戶願意花兩小時跟你出門」的證據，
    # 比任何口頭表達的興趣都硬。少了這一格，
    # 「傳過資料給他」跟「他已經跟你看過三間」會被歸在同一個階段。
    VIEWING = "VIEWING"
    # 買方下了斡旋金，等仲介去跟屋主談。畫面上顯示「斡旋中」。
    #
    # 不叫「議價」是因為那是**對屋主**做的事（殺價），
    # 買方端不會有議價的需求。這個 CRM 目前只管買方，用錯詞的話，
    # 業務看到那一格會以為是屋主端的資料。
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


class Urgency(str, Enum):
    """客戶對「多久要買到」表達出的態度。

    為什麼不直接用 purchase_timeline 就好？

    因為真實客戶很少會講「我三個月內要買到房子」。
    他們講的是「我下個月要過去上班，所以有點急」——
    有明確的急迫感，卻沒有任何可以填進 purchase_timeline 的月數。
    只靠月數的話，這種客戶在 Lead Score 上會被當成「沒有時間壓力」，
    排在該優先聯絡的名單後面。

    這跟 budget_is_approximate 是同一招：不讓 AI 去推算數字，
    而是讓它記錄客戶的語氣，換算與計分交給 Rule Engine。

    刻意只分兩級加上 null。分越細，AI 判斷錯的機率越高，
    而這一欄本來就比其他欄位主觀。
    """

    HIGH = "HIGH"  # 明確表達急迫：有點急、越快越好、這個月、下個月要搬
    LOW = "LOW"  # 明確表達不急：不急、明年再說、有物件再通知我
    # 沒有表達任何時間態度時是 null。
    # 「客戶說不急」與「客戶沒提到」必須分得開 —— 業務對這兩種人的處理方式不同。


class PropertyType(str, Enum):
    """房屋類型。

    只收這六類，是因為 AI 的輸出必須落在可列舉的集合裡：
    若允許自由字串，「電梯大樓」「大樓」「電梯華廈」會變成三個不同的值，
    Sprint 4 算準確率時就無法比對，日後要做物件搜尋也沒辦法下條件。
    """

    ELEVATOR_BUILDING = "ELEVATOR_BUILDING"  # 電梯大樓
    LOW_RISE = "LOW_RISE"  # 華廈
    APARTMENT = "APARTMENT"  # 公寓（無電梯）
    TOWNHOUSE = "TOWNHOUSE"  # 透天厝
    VILLA = "VILLA"  # 別墅
    STUDIO = "STUDIO"  # 套房


class Purpose(str, Enum):
    """購屋目的。AI 解析自然語言後會填入這個欄位。"""

    SELF_USE = "SELF_USE"  # 自住
    INVESTMENT = "INVESTMENT"  # 投資
    BOTH = "BOTH"
    UNKNOWN = "UNKNOWN"
