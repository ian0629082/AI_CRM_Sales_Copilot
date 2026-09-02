"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Toaster } from "@/components/ui/sonner";
import { setSlowRequestHandler } from "@/lib/api/client";
import { AuthProvider } from "@/lib/auth-context";

/**
 * 請求太慢時告訴使用者發生什麼事。
 *
 * Render 免費方案閒置 15 分鐘就休眠，之後第一個請求要等 50 秒以上。
 * 沒有這個提示的話，畫面上只有一顆變灰的按鈕 ——
 * 使用者（包含點開作品的面試官）會直接認定它壞了然後關掉。
 *
 * 講清楚「為什麼慢」跟「要等多久」，等待才會變成可以忍受的事。
 */
function useWakeUpNotice() {
  useEffect(() => {
    // 用計數而不是單一 id：同時有兩個慢請求時，
    // 先回來的那個不該把提示收掉，後面那個還在等。
    let pending = 0;
    let toastId: string | number | undefined;

    setSlowRequestHandler((phase) => {
      if (phase === "start") {
        pending += 1;
        toastId ??= toast.loading("伺服器正在喚醒，請稍候…", {
          description:
            "免費方案閒置一段時間會休眠，第一個請求大約要等 50 秒。醒來之後就會恢復正常速度。",
          duration: Infinity,
        });
        return;
      }

      pending = Math.max(0, pending - 1);
      if (pending === 0 && toastId !== undefined) {
        toast.dismiss(toastId);
        toastId = undefined;
      }
    });

    return () => setSlowRequestHandler(null);
  }, []);
}

export function Providers({ children }: { children: React.ReactNode }) {
  useWakeUpNotice();

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
