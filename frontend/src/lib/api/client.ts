/**
 * 與後端溝通的唯一入口。
 *
 * 所有 API 呼叫都經過這裡，好處是 token 附加、錯誤轉換、401 處理
 * 這些事只需要寫一次，不必散落在每個頁面。
 */

import { clearToken, getToken } from "@/lib/auth-storage";

const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL;

if (!BASE_URL) {
  throw new Error("缺少環境變數 NEXT_PUBLIC_API_BASE_URL，請檢查 .env.local");
}

/** 後端回傳的錯誤。保留 status 讓呼叫端可以區分處理（例如 404 顯示空狀態）。 */
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    /**
     * 後端這次請求的追查代碼（回應的 x-request-id）。
     *
     * 只有伺服器自己知道的 id 等於白做 —— 使用者說「我剛剛按下去壞了」，
     * 而 Render 的面板上是幾百行來自不同人、交錯在一起的訊息。
     * 把這組代碼顯示出來，那些孤立的句子才能被接回同一次請求。
     */
    public requestId?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/**
 * 「請求變慢了」的通知。
 *
 * 這裡不直接呼叫 toast：api client 不應該知道 UI 用什麼套件顯示訊息。
 * 由 Providers 在啟動時註冊，測試或其他環境可以不註冊。
 */
type SlowRequestHandler = (phase: "start" | "end") => void;

let slowRequestHandler: SlowRequestHandler | null = null;

export function setSlowRequestHandler(handler: SlowRequestHandler | null) {
  slowRequestHandler = handler;
}

/**
 * 幾秒之後才算「慢」。
 *
 * 抓 8 秒是因為兩件事都要顧到：後端就算是醒著的，登入本身也要 3 秒
 * （bcrypt 故意算得慢，那是它的安全價值），所以門檻太低會對正常請求
 * 也跳提示；而 Render 免費方案休眠後的喚醒是 50 秒以上，
 * 使用者在那之前只看得到一顆不動的按鈕。
 */
const SLOW_REQUEST_MS = 8000;

/**
 * 從後端的錯誤回應中取出可讀的訊息。
 *
 * 後端有兩種錯誤格式：
 * - 自訂錯誤：{ "detail": "Lead 3 不存在" }
 * - Pydantic 驗證錯誤（422）：{ "detail": [{ "loc": [...], "msg": "..." }] }
 */
function extractErrorMessage(body: unknown, status: number): string {
  if (typeof body === "object" && body !== null && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;

    if (typeof detail === "string") return detail;

    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) =>
          typeof item === "object" && item !== null && "msg" in item
            ? String((item as { msg: unknown }).msg)
            : null,
        )
        .filter(Boolean);
      if (messages.length > 0) return messages.join("；");
    }
  }
  return `請求失敗（HTTP ${status}）`;
}

type RequestOptions = {
  method?: string;
  body?: unknown;
  /** 401 時是否自動清除 token。登入頁本身要關掉，否則會蓋掉「密碼錯誤」的訊息。 */
  clearTokenOn401?: boolean;
};

export async function apiRequest<T>(
  path: string,
  { method = "GET", body, clearTokenOn401 = true }: RequestOptions = {},
): Promise<T> {
  const token = getToken();

  // 超過門檻才通知，而且只在真的通知過的時候才收回 ——
  // 否則每一個正常的請求都會讓畫面閃一下。
  let notified = false;
  const slowTimer = setTimeout(() => {
    notified = true;
    slowRequestHandler?.("start");
  }, SLOW_REQUEST_MS);

  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method,
      headers: {
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } finally {
    // 用 finally：請求失敗時也要收掉提示，
    // 不然一個斷線的請求會在畫面上留下一句「正在喚醒」永遠不消失。
    clearTimeout(slowTimer);
    if (notified) slowRequestHandler?.("end");
  }

  // 後端每個回應都帶這個 header（CORS 那邊也特地 expose 了它）。
  const requestId = response.headers.get("x-request-id") ?? undefined;

  if (response.status === 401 && clearTokenOn401) {
    // token 過期或無效，清掉以免後續每一支 API 都拿它去撞牆
    clearToken();
  }

  // 204 No Content 沒有 body，直接解析 JSON 會拋錯
  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  const data = text ? JSON.parse(text) : null;

  if (!response.ok) {
    throw new ApiError(
      response.status,
      extractErrorMessage(data, response.status),
      requestId,
    );
  }

  return data as T;
}
