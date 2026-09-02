"use client";

import { toast } from "sonner";

import { ApiError } from "@/lib/api/client";

/**
 * 出事時把追查代碼顯示給使用者。
 *
 * Sprint 6 讓每個回應都帶回 request_id，但只有伺服器知道的 id 等於白做。
 * 使用者只會說「我剛剛按下去壞掉了」，而 Render 的面板上是幾百行
 * 來自不同人、不同請求、交錯在一起的訊息 —— 有了這組代碼，
 * 那些孤立的句子才能被接回同一次請求。
 *
 * **只在 5xx 顯示。** 4xx 是使用者自己解決得了的事（密碼打錯、
 * 額度用完、資料不齊），對他附一組代碼只會製造噪音，
 * 而且會讓人以為那是系統故障。
 * 代碼要出現在「他真的需要找人幫忙」的時候才有意義。
 */
export function RequestIdHint({ error }: { error: unknown }) {
  if (!(error instanceof ApiError)) return null;
  if (error.status < 500 || !error.requestId) return null;

  const code = error.requestId;

  return (
    <button
      type="button"
      onClick={() => {
        void navigator.clipboard.writeText(code);
        toast.success("追查代碼已複製");
      }}
      className="text-xs text-muted-foreground underline-offset-2 hover:underline"
      title="點一下複製，回報問題時附上這組代碼"
    >
      追查代碼 {code}
    </button>
  );
}
