"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

import { Toaster } from "@/components/ui/sonner";
import { AuthProvider } from "@/lib/auth-context";

export function Providers({ children }: { children: React.ReactNode }) {
  // 用 useState 建立 QueryClient，而不是寫在模組頂層。
  // 模組頂層的實例會被同一個伺服器上的所有請求共用，
  // 在正式環境會造成不同使用者看到彼此的快取資料。
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // 資料庫在新加坡，每次查詢都有幾十毫秒延遲。
            // 30 秒內視為新鮮，避免切換頁面就重打一次 API。
            staleTime: 30_000,
            // 401 之類的錯誤重試沒有意義，只會拖慢錯誤顯示
            retry: 1,
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>{children}</AuthProvider>
      <Toaster position="top-center" richColors />
    </QueryClientProvider>
  );
}
