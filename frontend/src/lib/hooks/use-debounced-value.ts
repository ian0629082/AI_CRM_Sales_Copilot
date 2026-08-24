"use client";

import { useEffect, useState } from "react";

/**
 * 延遲回傳輸入值，直到它停止變動一段時間為止。
 *
 * 用在搜尋框：使用者每打一個字都觸發 API 太浪費，
 * 等他停下來再送出即可。
 */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    // 值又變了就取消上一次的計時，重新計算
    return () => clearTimeout(timer);
  }, [value, delayMs]);

  return debounced;
}
