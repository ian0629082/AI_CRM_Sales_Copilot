/**
 * JWT token 的存取。
 *
 * 為什麼用 localStorage 而不是 httpOnly cookie：
 * 前端部署在 Vercel、後端在 Render，兩者是不同網域。跨網域 cookie 需要
 * SameSite=None，而現代瀏覽器的第三方 cookie 限制會直接擋掉它 ——
 * Demo 時很可能在對方的瀏覽器上根本登不進去。
 *
 * 代價是 localStorage 可被 XSS 讀取。正式產品的作法會是把前端與 API
 * 收在同一個網域下（BFF 或反向代理），再改用 httpOnly cookie。
 *
 * 所有函式都要能在伺服器端安全執行（Next.js 會在 server 先跑一次），
 * 所以每個都先檢查 window 是否存在。
 */

const TOKEN_KEY = "crm_access_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(TOKEN_KEY);
}
