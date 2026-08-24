"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/lib/auth-context";

/**
 * 需要登入才能進入的區域。
 *
 * 保護只做在這一層，底下的頁面就不必各自檢查登入狀態。
 *
 * 注意這是「用戶體驗層級」的保護，不是安全防線 ——
 * 真正的防線在後端：沒有有效 token 的請求一律回 401。
 * 前端的檢查只是為了不要讓使用者看到一片空白的畫面。
 */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user, isLoading, logout } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !user) router.replace("/login");
  }, [isLoading, user, router]);

  if (isLoading || !user) {
    return (
      <div className="flex min-h-screen flex-col">
        <div className="border-b">
          <div className="mx-auto flex h-14 max-w-6xl items-center px-4">
            <Skeleton className="h-5 w-40" />
          </div>
        </div>
        <div className="mx-auto w-full max-w-6xl space-y-4 p-4">
          <Skeleton className="h-8 w-48" />
          <Skeleton className="h-64 w-full" />
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col bg-muted/20">
      <header className="border-b bg-background">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4">
          <nav className="flex items-center gap-6">
            <Link href="/leads" className="font-semibold">
              AI CRM Sales Copilot
            </Link>
            <Link
              href="/leads"
              className="text-sm text-muted-foreground transition-colors hover:text-foreground"
            >
              客戶管理
            </Link>
          </nav>

          <div className="flex items-center gap-3">
            <span className="hidden text-sm text-muted-foreground sm:inline">
              {user.name}
            </span>
            <Button variant="ghost" size="sm" onClick={logout}>
              登出
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 p-4">{children}</main>
    </div>
  );
}
