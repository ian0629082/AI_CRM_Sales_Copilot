# 部署步驟

> 後端 Render、前端 Vercel、資料庫 Neon（已在雲端，不動它）。
> 設定值的說明在 [render.yaml](../render.yaml) 與兩份 `.env.example` 的註解裡，
> 這份文件只講「按什麼順序做、怎麼確認成功」。

**順序不能反：先後端、再前端、最後回頭改一個值。**
前端先上的話會拿到 CORS 錯誤，而那種錯誤在瀏覽器上看起來像「後端掛了」——
你手上還沒有一個已知正常的後端可以對照，等於一開始就把兩個變數綁在一起。

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

1. Vercel → New Project，選同一個 repo，**Root Directory 設成 `frontend`**。
2. 環境變數只有一個：

   ```
   NEXT_PUBLIC_API_BASE_URL = https://<你的服務>.onrender.com/api/v1
   ```

   **結尾的 `/api/v1` 不能漏**，本機 `.env.local` 也是這個格式。

3. 部署完成後先不要急著登入，見下一步。

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
