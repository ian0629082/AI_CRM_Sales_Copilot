# 部署步驟

> 後端 Render、前端 Vercel、資料庫 Neon（已在雲端，不動它）。
> 設定值的說明在 [render.yaml](../render.yaml) 與兩份 `.env.example` 的註解裡，
> 這份文件只講「按什麼順序做、怎麼確認成功」。

**順序不能反：先後端、再前端、最後回頭改一個值。**
前端先上的話會拿到 CORS 錯誤，而那種錯誤在瀏覽器上看起來像「後端掛了」——
你手上還沒有一個已知正常的後端可以對照，等於一開始就把兩個變數綁在一起。

---

## 零、免費方案的限制，以及它們各自造成的後果

查過 Render 文件之後確認的四件事，它們不只是「限制」，
每一條都已經改變了這個專案的某個決定：

| 限制 | 後果 |
|---|---|
| 15 分鐘沒有流量就休眠，喚醒**約一分鐘** | 前端必須自己顯示喚醒提示（見下方第五節） |
| 每個 workspace 每月 **750 instance 小時** | 一個服務整月開著約 730 小時，剛好在額度內 —— 但這也表示**不能靠定時 ping 讓它永不休眠**，那會把額度用到貼著上限，而且再開第二個免費服務就會兩個一起被停 |
| 不能跑 one-off job | 「每天重置 Demo 資料」不能用 Render 的排程，要用 GitHub Actions 直接連 Neon |
| 沒有 shell、檔案系統重開就清空 | migration 只能放在 `buildCommand`（`render.yaml` 裡已經是這樣，理由寫在該檔註解），而且資料庫非用 Neon 不可 |

---

## 一、後端上 Render

1. Render → New → Blueprint，選這個 repo。它會讀根目錄的 `render.yaml`。
2. 三個 `sync: false` 的值要手動填（Blueprint 刻意不帶它們，因為含密碼）：

   | 變數 | 填什麼 |
   |---|---|
   | `DATABASE_URL` | Neon 的連線字串，**開頭要改成 `postgresql+psycopg://`** |
   | `OPENAI_API_KEY` | 你的 key |
   | `CORS_ORIGINS` | 先填 `http://localhost:3000`，等 Vercel 上線再改 |

   `JWT_SECRET` 不用填，Render 會自己產一組——刻意不沿用本機那組。

3. 部署完成後開 `https://<你的服務>.onrender.com/health`，要看到 200。

> `/health` 不碰資料庫也不碰 OpenAI，所以它回 200 只代表**程式起來了**。
> 資料庫通不通要下一步才知道。

4. 開 `https://<你的服務>.onrender.com/docs`，用 `POST /auth/login` 打一次 demo 帳號。
   **這一步才真的驗證了 `DATABASE_URL`**——登入要查使用者表。

### 這一步可能會卡的地方

- **連線字串忘了改 `+psycopg`**：build 時 `alembic upgrade head` 會失敗。
- **build 過了但服務起不來**：多半是 `JWT_SECRET` 或 `DATABASE_URL` 沒設，
  `config.py` 在啟動時就會擋下來。看 Render 的 Logs，錯誤訊息會直接指出是哪一個。

---

## 二、前端上 Vercel

Import 的時候找不到設定欄位是正常的，Vercel 把它們都放在專案建好之後的
**Settings** 裡。三件事要**一次設完再重新部署**，不要改一項部署一次：

| 位置 | 設定 |
|---|---|
| Settings → **Build and Deployment** → Root Directory | `frontend` |
| Settings → **Environments** → Production → Branch Tracking | 目前的部署分支 |
| Settings → **Environments** → Production → Environment Variables | `NEXT_PUBLIC_API_BASE_URL` = `https://<你的服務>.onrender.com/api/v1` |

**結尾的 `/api/v1` 不能漏**，本機 `.env.local` 也是這個格式。
漏了的話每支 API 都會 404，症狀看起來像後端掛了。

### 這一段有三個地方會卡

**一、`NEXT_PUBLIC_API_BASE_URL` 的 Type 要選 `Config`，不要選 `Secret`。**
`NEXT_PUBLIC_` 開頭的變數會被編譯進瀏覽器看得到的程式碼，它本來就是公開的。
選 Secret 除了自己再也看不到值，更糟的是把一個公開值標成祕密 ——
下次讀設定的人會分不清哪些才是真的要保護的東西。

**二、設完環境變數一定要重新部署。**
`NEXT_PUBLIC_*` 是**建置時**寫進程式碼的，不是執行時讀的。
只存檔不重建，畫面上不會有任何變化。

**三、改了 Branch Tracking 之後，要推一個新 commit 才會生效。**
改設定不會自己觸發部署，而對著舊的失敗紀錄按 Redeploy，
重跑的仍然是**那一次的 commit**（也就是舊分支的內容）。

> 這一條特別容易誤判，因為 `main` 上的程式碼通常**建得起來**，
> 只是少了還沒合併進去的功能 —— 你會拿到一個看起來正常、
> 功能卻少一半的網站，而且沒有任何錯誤訊息提醒你。

網域還沒有任何一次成功部署時，開起來會是 Vercel 的 404，
回應標頭寫著 `X-Vercel-Error: DEPLOYMENT_NOT_FOUND` ——
看到這個就是「設定可能都對了，但還沒真的建成功過」，不是程式的問題。

---

## 三、回頭把 `CORS_ORIGINS` 改成 Vercel 的網域

Render → Environment → `CORS_ORIGINS` 改成 `https://<你的專案>.vercel.app`，
存檔後服務會自動重啟。

這兩邊互相指向，所以中間一定會有一次要回頭改——不是漏想，是順序本身的必然。

> 不要填 `*`。那等於允許任何網站代替已登入的使用者呼叫這個 API。

**Vercel 的 preview 網域每次部署都不一樣**，所以 preview 版本會被 CORS 擋掉。
只驗正式網域是刻意的：要在 preview 上測就把那個網址也加進去（逗號分隔），
但不要為了省事填萬用字元。

---

## 四、上線後的驗收清單

照這個順序點一次，每一項對應一條剛接上的線：

| 動作 | 通過代表什麼 |
|---|---|
| 打開首頁 | Vercel 部署成功 |
| 登入 demo 帳號 | 前端找得到後端、CORS 沒擋、資料庫通 |
| 客戶列表出得來 | 認證與查詢都正常 |
| 進客戶詳細頁按「AI 解析」 | `OPENAI_API_KEY` 有設對 |
| 按「跟進建議」 | 同上，而且沒有超過每日上限 |
| 故意打一個不存在的客戶 id | 回 404 而不是 500 |

任何一項失敗，先看 Render 的 Logs，用畫面上顯示的 `request_id` 去搜——
那組代碼就是為了這種時候存在的。

---

## 四之二、每天重置 Demo 資料

登入頁有「直接看 Demo」，所以任何人都能改那 32 筆客戶。
改壞了不會有人通知你，而下一個點開作品的人看到的就是那個樣子。

排程在 [.github/workflows/reset-demo.yml](../.github/workflows/reset-demo.yml)，
每天台北時間清晨 04:00 跑一次，也可以在 GitHub 的 Actions 頁手動觸發。

**要先加一個 secret**：GitHub → Settings → Secrets and variables → Actions →
New repository secret，名稱 `DATABASE_URL`，值就是 Neon 那串
（同樣要 `postgresql+psycopg://` 開頭）。沒加的話這個 workflow 每天都會失敗。

> 它直接連 Neon，不經過 Render —— 免費方案不能跑 one-off job，
> 而且這樣後端在休眠也不影響重置。

**一個副作用要知道**：重置會連帶刪掉那些客戶的 `ai_analysis` 紀錄，
而每日的 AI 建議額度就是用那張表算的，所以額度會在重置時一併歸零。
清晨四點沒有人在用，影響可以忽略，但別在看到「用完了卻又能按」時感到困惑。

---

## 五、合併回 main 之後一定要做的事

部署期間 Render 與 Vercel 都綁在 `feature/deployment` 上。
全部驗完、合併進 `develop` 再進 `main` 之後，**兩邊都要改回 `main`**：

| 平台 | 位置 |
|---|---|
| Render | Settings → Branch |
| Vercel | Settings → Environments → Production → Branch Tracking |

不改的話正式站會永遠跟著一個 feature 分支跑 —— 而那個分支之後不會再更新，
於是「已經合併進 main 的修正沒有上線」，卻看不出任何異常。
