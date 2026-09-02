"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/lib/auth-context";

/**
 * 首頁只負責分流：已登入去客戶列表，未登入去登入頁。
 *
 * 這裡必須是 Client Component —— 登入狀態存在 localStorage，
 * 伺服器端無從得知，只能在瀏覽器裡判斷。
 */
export default function HomePage() {
  const { user, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (isLoading) return;
    router.replace(user ? "/dashboard" : "/login");
  }, [user, isLoading, router]);

  return (
    <div className="flex min-h-screen items-center justify-center">
      <Skeleton className="h-8 w-48" />
    </div>
  );
}
