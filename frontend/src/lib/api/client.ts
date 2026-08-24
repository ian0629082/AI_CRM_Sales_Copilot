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
  ) {
    super(message);
    this.name = "ApiError";
  }
}

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

  const response = await fetch(`${BASE_URL}${path}`, {
    method,
    headers: {
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

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
    throw new ApiError(response.status, extractErrorMessage(data, response.status));
  }

  return data as T;
}
