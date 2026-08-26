"use client";

/**
 * 登入狀態的單一來源。
 *
 * 這裡只做三件事：目前是誰、怎麼登入、怎麼登出。
 * 頁面層級的權限保護放在 (app)/layout.tsx，不混在這裡。
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext } from "react";

import * as authApi from "@/lib/api/auth";
import { clearToken, getToken, setToken } from "@/lib/auth-storage";
import type { User } from "@/lib/api/types";

type AuthContextValue = {
  user: User | null;
  /** 尚未確定登入狀態（正在用 token 向後端確認）。 */
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const queryClient = useQueryClient();

  const { data: user, isLoading } = useQuery({
    queryKey: ["me"],
    queryFn: authApi.getMe,
    // 沒有 token 就不必問後端，直接視為未登入
    enabled: typeof window !== "undefined" && getToken() !== null,
    retry: false,
    staleTime: 5 * 60_000,
  });

  const login = useCallback(
    async (email: string, password: string) => {
      const { access_token } = await authApi.login({ email, password });
      setToken(access_token);
      // 重新抓取使用者資料，讓 UI 立刻反映登入狀態
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      router.push("/dashboard");
    },
    [queryClient, router],
  );

  const logout = useCallback(() => {
    clearToken();
    // 清掉所有快取，否則下一個登入的人會先看到前一個人的客戶資料
    queryClient.clear();
    router.push("/login");
  }, [queryClient, router]);

  return (
    <AuthContext.Provider
      value={{ user: user ?? null, isLoading, login, logout }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (ctx === null) {
    throw new Error("useAuth 必須在 AuthProvider 之內使用");
  }
  return ctx;
}
