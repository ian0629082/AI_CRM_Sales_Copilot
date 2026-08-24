import { apiRequest } from "@/lib/api/client";
import type { Token, User } from "@/lib/api/types";

export function register(payload: {
  name: string;
  email: string;
  password: string;
}): Promise<User> {
  return apiRequest<User>("/auth/register", {
    method: "POST",
    body: payload,
    // 註冊頁不該因為後端回 401 就去動 token
    clearTokenOn401: false,
  });
}

export function login(payload: {
  email: string;
  password: string;
}): Promise<Token> {
  return apiRequest<Token>("/auth/login", {
    method: "POST",
    body: payload,
    // 登入失敗回的就是 401，這時清 token 沒有意義，
    // 反而會讓錯誤處理變得難以理解
    clearTokenOn401: false,
  });
}

export function getMe(): Promise<User> {
  return apiRequest<User>("/auth/me");
}
