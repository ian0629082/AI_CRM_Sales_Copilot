"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api/client";
import { useAuth } from "@/lib/auth-context";

const loginSchema = z.object({
  email: z.string().min(1, "請輸入 email").email("email 格式不正確"),
  password: z.string().min(1, "請輸入密碼"),
});

type LoginForm = z.infer<typeof loginSchema>;

/**
 * 公開的展示帳號。
 *
 * 直接寫在前端不是疏忽：這組帳密本來就是要給所有人用的，
 * 藏起來只會讓想看作品的人多一道無謂的手續。
 * 它保護的東西是「其他人的資料」，而那是後端 owner_id 過濾在守的，
 * 不是靠這組帳密沒人知道。
 */
const DEMO_ACCOUNT = { email: "demo@example.com", password: "demo1234" };

export default function LoginPage() {
  const { login, user, isLoading } = useAuth();
  const router = useRouter();
  const [serverError, setServerError] = useState<string | null>(null);
  const [demoPending, setDemoPending] = useState(false);

  // 已經登入的人不該再看到登入頁
  useEffect(() => {
    if (!isLoading && user) router.replace("/dashboard");
  }, [isLoading, user, router]);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginForm>({ resolver: zodResolver(loginSchema) });

  async function onSubmit(values: LoginForm) {
    setServerError(null);
    try {
      await login(values.email, values.password);
    } catch (error) {
      // 後端對「帳號不存在」與「密碼錯誤」回傳相同訊息，
      // 這裡直接照原樣顯示，不要自作聰明去區分
      setServerError(
        error instanceof ApiError ? error.message : "登入失敗，請稍後再試",
      );
    }
  }

  async function onTryDemo() {
    setServerError(null);
    setDemoPending(true);
    try {
      await login(DEMO_ACCOUNT.email, DEMO_ACCOUNT.password);
    } catch (error) {
      setServerError(
        error instanceof ApiError ? error.message : "登入失敗，請稍後再試",
      );
    } finally {
      setDemoPending(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-muted/30 p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-2xl">登入</CardTitle>
          <CardDescription>AI CRM Sales Copilot</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                autoComplete="email"
                placeholder="you@example.com"
                aria-invalid={Boolean(errors.email)}
                {...register("email")}
              />
              {errors.email ? (
                <p className="text-sm text-destructive">{errors.email.message}</p>
              ) : null}
            </div>

            <div className="space-y-2">
              <Label htmlFor="password">密碼</Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                aria-invalid={Boolean(errors.password)}
                {...register("password")}
              />
              {errors.password ? (
                <p className="text-sm text-destructive">{errors.password.message}</p>
              ) : null}
            </div>

            {serverError ? (
              <p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {serverError}
              </p>
            ) : null}

            <Button
              type="submit"
              className="w-full"
              disabled={isSubmitting || demoPending}
            >
              {isSubmitting ? "登入中..." : "登入"}
            </Button>
          </form>

          {/* 一鍵進入放在表單之後、而且是次要樣式：
              真正要用這個系統的人是輸入自己的帳密，
              展示帳號是給「先看看這是什麼」的人用的。

              但它必須存在 —— 一個要求先註冊才能看的作品集，
              大部分人在註冊那一步就關掉了。 */}
          <div className="mt-4 space-y-2">
            <Button
              type="button"
              variant="outline"
              className="w-full"
              onClick={onTryDemo}
              disabled={isSubmitting || demoPending}
            >
              {demoPending ? "準備中..." : "直接看 Demo"}
            </Button>
            <p className="text-center text-xs text-muted-foreground">
              用展示帳號登入，裡面有 32 位虛構客戶可以操作
            </p>
          </div>

          <p className="mt-4 text-center text-sm text-muted-foreground">
            還沒有帳號？
            <Link href="/register" className="ml-1 text-primary hover:underline">
              註冊
            </Link>
          </p>
        </CardContent>
      </Card>
    </main>
  );
}
