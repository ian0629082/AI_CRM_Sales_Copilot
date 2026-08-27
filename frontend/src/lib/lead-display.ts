/**
 * 後端 enum 值對應到畫面上的中文與樣式。
 *
 * 後端傳的是 NEW / CONTACTED 這種穩定的英文代碼，翻譯成中文是前端的責任。
 * 好處是日後要做多語系，只需要換掉這個檔案。
 */

import type {
  InteractionType,
  LeadLevel,
  LeadSource,
  LeadStatus,
  PropertyType,
  Purpose,
  Urgency,
} from "@/lib/api/types";

/** Lead Funnel 的順序，列表篩選與 Dashboard 都依這個順序呈現。 */
export const LEAD_STATUS_ORDER: LeadStatus[] = [
  "NEW",
  "CONTACTED",
  "INTERESTED",
  "MEETING",
  "NEGOTIATING",
  "WON",
  "LOST",
];

export const LEAD_STATUS_LABEL: Record<LeadStatus, string> = {
  NEW: "新客戶",
  CONTACTED: "已聯絡",
  INTERESTED: "有興趣",
  MEETING: "已約訪",
  NEGOTIATING: "斡旋中",
  WON: "成交",
  LOST: "流失",
};

/** 用 Tailwind class 而非顏色名稱，讓深淺色模式都能正確顯示。 */
export const LEAD_STATUS_CLASS: Record<LeadStatus, string> = {
  NEW: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200",
  CONTACTED: "bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-200",
  INTERESTED: "bg-cyan-100 text-cyan-700 dark:bg-cyan-950 dark:text-cyan-200",
  MEETING: "bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-200",
  NEGOTIATING: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200",
  WON: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-200",
  LOST: "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-200",
};

export const LEAD_LEVEL_LABEL: Record<LeadLevel, string> = {
  HOT: "高意願",
  WARM: "中意願",
  COLD: "低意願",
};

export const LEAD_SOURCE_LABEL: Record<LeadSource, string> = {
  WEB_FORM: "網路表單",
  PHONE: "電話",
  REFERRAL: "轉介",
  WALK_IN: "來店",
  LINE: "LINE",
  OTHER: "其他",
};

export const PURPOSE_LABEL: Record<Purpose, string> = {
  SELF_USE: "自住",
  INVESTMENT: "投資",
  BOTH: "自住兼投資",
  UNKNOWN: "未確定",
};

export const PROPERTY_TYPE_LABEL: Record<PropertyType, string> = {
  ELEVATOR_BUILDING: "電梯大樓",
  LOW_RISE: "華廈",
  APARTMENT: "公寓",
  TOWNHOUSE: "透天厝",
  VILLA: "別墅",
  STUDIO: "套房",
};

/**
 * 客戶表達出的急迫程度。
 *
 * 跟「預計時程」是兩回事：時程是客戶講出來的月數，急迫程度是他的語氣。
 * 真實客戶很少講「我三個月內要買到」，但常常講「有點急」——
 * 少了這一欄，那種客戶在 Lead Score 上會被當成沒有時間壓力。
 */
export const URGENCY_LABEL: Record<Urgency, string> = {
  HIGH: "急",
  LOW: "不急",
};

export const URGENCY_CLASS: Record<Urgency, string> = {
  HIGH: "bg-orange-100 text-orange-700 dark:bg-orange-950 dark:text-orange-200",
  LOW: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
};

/**
 * 分數的顏色。
 *
 * 用等級而不是分數區間決定顏色，這樣改門檻時只要改後端一個地方，
 * 前端不會偷偷跟後端不同步。
 */
export const LEAD_LEVEL_CLASS: Record<LeadLevel, string> = {
  HOT: "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-200",
  WARM: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200",
  COLD: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
};

/** 待跟進清單的分類標題。兩堆對應兩種不同的業務動作，標題要講得出差別。 */
export const FOLLOW_UP_BUCKET_LABEL: Record<string, string> = {
  NEW_UNCONTACTED: "新進未聯絡",
  DUE: "到期跟進",
};

export const INTERACTION_TYPE_LABEL: Record<InteractionType, string> = {
  CALL: "電話",
  LINE: "LINE",
  EMAIL: "Email",
  MEETING: "會面",
  VIEWING: "帶看",
  NOTE: "備註",
};

/**
 * 把金額轉成台灣習慣的「萬」為單位。
 *
 * 20000000 -> "2,000 萬"
 * 房仲場景幾乎不會用到「元」，全部顯示原始數字反而難讀。
 */
export function formatBudget(amount: number | null | undefined): string {
  if (amount === null || amount === undefined) return "—";
  const wan = amount / 10000;
  return `${wan.toLocaleString("zh-TW", { maximumFractionDigits: 0 })} 萬`;
}

/**
 * 預算區間。只有下限或只有上限時也要能正確顯示。
 *
 * isApproximate 為 true 時前面加「約」：客戶說的是「2000 萬左右」，
 * 畫面就不該顯示得像是一個精確數字。真正的 5% 搜尋緩衝由後端的
 * Rule Engine 計算，這裡只負責誠實呈現客戶原本的語氣。
 */
export function formatBudgetRange(
  min: number | null | undefined,
  max: number | null | undefined,
  isApproximate = false,
): string {
  const prefix = isApproximate ? "約 " : "";

  if (min === null || min === undefined) {
    if (max === null || max === undefined) return "—";
    return `${prefix}${formatBudget(max)} 以下`;
  }
  if (max === null || max === undefined) return `${prefix}${formatBudget(min)} 以上`;
  if (min === max) return `${prefix}${formatBudget(min)}`;
  return `${prefix}${formatBudget(min)} ~ ${formatBudget(max)}`;
}

/** 後端回傳 UTC 時間，這裡轉成本地時區顯示。 */
export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("zh-TW", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("zh-TW", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}
