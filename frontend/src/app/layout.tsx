import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { Providers } from "@/app/providers";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "AI CRM Sales Copilot",
  description: "AI 驅動的房仲業務 CRM 助手",
  other: {
    // 這一版是從哪個分支、哪個 commit 建出來的。
    //
    // Vercel 在建置時注入這兩個變數（本機是 undefined）。放進 meta 而不是
    // 畫面上：它是給查問題的人看的，不是給使用者看的 —— 但要看得到，
    // 因為部署平台跟著哪個分支只有登入平台的人才知道，
    // 而「以為它跟著 main」跟「其實跟著別的分支」在外面長得一模一樣。
    //
    // NEXT_PUBLIC_ 前綴的變數會被編譯進瀏覽器程式碼，所以這裡只能放
    // 公開資訊 —— 分支名與 commit 短碼本來就寫在 GitHub 上。
    "x-build-branch": process.env.NEXT_PUBLIC_VERCEL_GIT_COMMIT_REF ?? "local",
    "x-build-commit": (
      process.env.NEXT_PUBLIC_VERCEL_GIT_COMMIT_SHA ?? "local"
    ).slice(0, 7),
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-TW">
      <body className={`${geistSans.variable} ${geistMono.variable} antialiased`}>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
