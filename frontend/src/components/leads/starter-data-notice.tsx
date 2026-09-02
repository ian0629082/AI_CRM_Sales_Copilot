"use client";

import { useState, useSyncExternalStore } from "react";

import { Button } from "@/components/ui/button";

const DISMISSED_KEY = "starter-data-notice-dismissed";

/**
 * localStorage 是「外部資料來源」，React 讀它的正規方式是 useSyncExternalStore，
 * 不是 useEffect + setState（那會在每次載入時多渲染一輪，
 * 而且新版的 lint 規則直接擋下來）。
 *
 * 伺服器端沒有 localStorage，所以 getServerSnapshot 一律回「已關閉」——
 * 這樣預渲染出來的 HTML 不含這張提示，接手之後才依實際狀態顯示。
 * 反過來（預設顯示）會讓每個已經關掉的人在重新整理時看到它閃一下。
 */
function subscribe(onChange: () => void) {
  // 只有「其他分頁改了它」才會觸發，本頁自己的改動靠下面的 state。
  window.addEventListener("storage", onChange);
  return () => window.removeEventListener("storage", onChange);
}

function readDismissed(): boolean {
  try {
    return localStorage.getItem(DISMISSED_KEY) === "1";
  } catch {
    // 無痕視窗或封鎖了儲存空間時會直接丟例外。
    // 那種情況顯示提示就好 —— 記不住總比整頁壞掉好。
    return false;
  }
}

/**
 * 告訴新使用者「這幾筆是系統幫你建的，可以刪」。
 *
 * 不標示的話會有一個很不舒服的狀態：他第一次登入就看到六位不認識的客戶，
 * 而系統從頭到尾沒有解釋那是什麼。有人會以為看到了別人的資料。
 *
 * 關掉的狀態存在瀏覽器（localStorage）而不是後端：
 * 它是這台裝置上的閱讀狀態，不是這個帳號的資料 ——
 * 為了它多開一個欄位、多一支 API，代價跟收益不成比例。
 * 代價是換一台電腦會再看到一次，那不算損失。
 */
export function StarterDataNotice() {
  const storedDismissed = useSyncExternalStore(subscribe, readDismissed, () => true);
  // 本頁自己按下「知道了」不會觸發 storage 事件，所以另外記一份。
  const [dismissedNow, setDismissedNow] = useState(false);

  if (storedDismissed || dismissedNow) return null;

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-l-4 border-border border-l-primary bg-muted p-3 text-sm">
      <p className="text-foreground/90">
        這幾位客戶是註冊時自動建立的<span className="font-medium">範例資料</span>
        ，可以直接編輯或刪除。
      </p>
      <Button
        size="sm"
        variant="outline"
        onClick={() => {
          setDismissedNow(true);
          try {
            localStorage.setItem(DISMISSED_KEY, "1");
          } catch {
            // 存不起來就算了，這一次的關閉仍然有效
          }
        }}
      >
        知道了
      </Button>
    </div>
  );
}
