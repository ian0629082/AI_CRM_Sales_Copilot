# AI CRM Sales Copilot

AI 驅動的房仲業務 CRM 助手：把客戶的自然語言需求轉成結構化資料，用 Rule Engine 計算 Lead Score，並產生 Follow-up 建議。

**線上版本**

| | |
|---|---|
| 前端 | <https://ai-crm-sales-copilot.vercel.app> |
| 後端 API 文件 | <https://ai-crm-backend-nl88.onrender.com/docs> |
| 展示帳號 | `demo@example.com` / `demo1234`（登入頁有「直接看 Demo」） |

> ⚠️ 後端跑在 Render 免費方案，閒置 15 分鐘會休眠，**第一個請求要等 50 秒以上**。
> 畫面會顯示「伺服器正在喚醒」的提示，不是壞掉。

完整規劃見 [AI_CRM_Sales_Copilot_開發規劃.md](AI_CRM_Sales_Copilot_開發規劃.md)，
開發進度與所有設計決策的理由見 [docs/PROGRESS.md](docs/PROGRESS.md)。

## 目前進度

| Sprint | 內容 | 狀態 |
|---|---|---|
| 0 | Planning（Business Problem / User Story / ERD / API Contract） | ✅ |
| 1 | CRM Core：Lead / Interaction CRUD、JWT 認證、Alembic | ✅ |
| 2 | Vertical Slice：Next.js 前端，前端到資料庫全鏈路跑通 | ✅ |
| 3 | AI Requirement Parsing | ✅ |
| 4 | AI Evaluation Dataset | ✅ |
| 5 | Lead Scoring + AI Follow-up 建議 | ✅ |
| 6 | Quality：Testing / Logging / Error Handling / Security | ✅ |
| 7 | Deployment：CI/CD、Vercel + Render 上線 | ✅ **← MVP 完成** |
| 8～11 | n8n / RAG / AI Copilot / Tool Calling Agent | ⬜ |

後端測試 **342 個**。

## 技術選擇

- **Backend**：Python 3.12 + FastAPI + SQLAlchemy 2.0
- **Database**：PostgreSQL 18（Neon, AWS ap-southeast-1 新加坡）
- **Frontend**：Next.js 16 + React 19 + TypeScript + Tailwind v4 + shadcn/ui
- **前端資料層**：TanStack Query（快取與重新驗證）+ react-hook-form + zod
- **Auth**：JWT（PyJWT）+ bcrypt 密碼雜湊
- **AI**：OpenAI Structured Output（strict JSON Schema）+ Pydantic 二次驗證
- **部署**：Vercel（前端）+ Render（後端）+ GitHub Actions（CI）

**沒有用 Docker**，理由寫在 [docs/PROGRESS.md](docs/PROGRESS.md) 的 Sprint 7 那一節 ——
這個專案的每一個預設用途都不成立，而放一個自己沒在用的 Dockerfile 只會腐爛。

## AI 功能與它們的評估

兩個 AI 功能，**性質不同，所以評估方式也不同**：

| | 需求解析 | 跟進建議 |
|---|---|---|
| 輸出 | 結構化欄位 | 自由文字 |
| 有標準答案嗎 | 有（人工標註） | **沒有** |
| 怎麼評估 | 逐欄位算準確率 | Criteria-based（一組判準） |

**可以引用的數字**（`gpt-5.4-mini`）：

| 功能 | 資料集 | 結果 |
|---|---|---|
| 需求解析 | 期末考 15 筆（出題者未讀過 prompt） | 欄位正確率 **97.0%**、完全正確率 **73.3%**、捏造率 **0%** |
| 跟進建議 | holdout 13 筆 | 捏造率 **0%**、六條判準全過 **92%** |

樣本都很小，引用時必須一併講樣本數與信賴區間。
完整報告、錯誤分析與**必須一起講的但書**在 [docs/evaluation/README.md](docs/evaluation/README.md)。

> 資料集分成三份（開發集 / holdout / 期末考）且不可混用。
> 期末考跑完後，完全正確率比 holdout **低了 22 個百分點** ——
> 那個落差就是「出題的人讀過 prompt」值多少分。

### AI 的使用量上限

每一次呼叫都是真的付費給 OpenAI，所以有兩道上限：

| | 上限 |
|---|---|
| 跟進建議（每人每天） | 10 次 |
| 跟進建議（全站每天） | 20 次 |

需求解析沒有另外設上限：同一段原話重複解析會直接讀快取，不會再呼叫模型。

## 後端啟動方式

```bash
cd backend

# 第一次執行才需要
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env          # 再把 DATABASE_URL 等填成真實值

# 建立/更新資料表（依 migration）
alembic upgrade head

# 啟動
uvicorn app.main:app --reload
```

啟動後開 <http://127.0.0.1:8000/docs> 看互動式 API 文件。

> 沒有設 `OPENAI_API_KEY` 也能跑完整個 CRM，只有兩顆 AI 按鈕會回 503。
> 這是刻意的：AI 是 Enhancement，不是地基。

## 前端啟動方式

```bash
cd frontend

# 第一次執行才需要
npm install
copy .env.example .env.local    # 預設值即可對應本機後端

npm run dev
```

開 <http://localhost:3000>。後端必須同時執行，否則登入會失敗。

## 常用腳本

```bash
cd backend

python -m scripts.seed_demo --reset        # 重建 32 筆 Demo 客戶
python -m scripts.rescore_leads            # 調整計分權重後，回填既有客戶的分數
python -m scripts.export_openapi           # 改了後端 schema 之後
python -m scripts.holdout_coverage         # 看判準覆蓋率（不花錢）
python -m scripts.evaluate_parsing --help  # 需求解析的準確率評估
python -m scripts.evaluate_followup --help # 跟進建議的 Criteria 評估
```

> 兩支 `evaluate` 會呼叫真實 OpenAI，**會花錢**。先加 `--limit 2` 確認流程通了再跑整份。

## 部署

設定寫在 [render.yaml](render.yaml)，步驟與踩過的坑寫在 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)。

CI（[.github/workflows/ci.yml](.github/workflows/ci.yml)）跑後端測試與前端建置，
**刻意不提供 `OPENAI_API_KEY`** —— 讓「沒有 key 時 CRM 仍然完整」那兩支測試在真實條件下跑，
順便讓 CI 不必碰祕密、也不會因模型的隨機性而變紅。

另一個排程每天清晨重置 Demo 資料（[reset-demo.yml](.github/workflows/reset-demo.yml)）：
登入頁開放一鍵進入，任何人都能改那 32 筆客戶。

## 前後端型別同步

後端的 OpenAPI schema 會生成前端的 TypeScript 型別。**改完後端的 schema 後要重跑**：

```bash
cd backend
python -m scripts.export_openapi     # 產生 frontend/openapi.json

cd ../frontend
npm run gen:api                      # 由 openapi.json 生成 src/types/api.ts
```

前端所有 API 型別都來自 `src/types/api.ts`，不要手寫。後端改了欄位，前端 `npm run build` 就會編譯失敗 —— 這正是要的效果，而不是等到打開畫面才發現一片空白。CI 也會檢查 `openapi.json` 有沒有跟後端一起更新。

## 認證方式與其取捨

JWT 存在 `localStorage`，以 `Authorization: Bearer` 標頭送出。

沒有採用 httpOnly cookie 的原因：前端部署在 Vercel、後端在 Render，兩者屬於不同網域。跨網域 cookie 需要 `SameSite=None`，而現代瀏覽器的第三方 cookie 限制會直接擋掉它。

代價是 `localStorage` 可被 XSS 讀取。正式產品的作法會是把前端與 API 收在同一網域下（BFF 或反向代理），再改用 httpOnly cookie。

## 資料庫 Migration

Schema 由 Alembic 管理，**不要手動改資料庫**。流程一律是：改 model → 產生 migration → 套用。

```bash
cd backend

# 套用所有尚未執行的 migration
alembic upgrade head

# 改完 model 後，自動比對差異並產生 migration（產生後務必打開檢查內容）
alembic revision --autogenerate -m "add xxx column"

# 查看目前版本 / 確認 model 與資料庫有無落差
alembic current
alembic check

# 退回上一版
alembic downgrade -1
```

連線字串從 `.env` 讀取，**不寫在 `alembic.ini`**（該檔案會進版控，不能有密碼）。

> `alembic.ini` 必須維持純 ASCII —— Alembic 用系統 locale 編碼（本機是 cp950）讀它，加中文註解會直接讓指令爆掉。

## 執行測試

```bash
cd backend
python -m pytest -q
```

測試不會呼叫真實的 OpenAI：`LLMProvider` 被換成假的，回傳固定 JSON。
「模型準不準」是評估腳本的職責，用的是另一套機制。

## 專案結構

```text
backend/
└── app/
    ├── main.py          # 只負責組裝 app，不放商業邏輯
    ├── api/             # HTTP 層：收發請求
    ├── services/        # 商業邏輯層
    ├── repositories/    # 資料庫存取層
    ├── models/          # SQLAlchemy ORM（資料庫長什麼樣）
    ├── schemas/         # Pydantic（API 對外承諾長什麼樣）
    ├── core/            # 設定、錯誤定義、安全性、log
    └── db/              # 連線與 Session
```

分層的用意：AI 是 Enhancement，不是地基。即使 LLM API 掛掉，CRM 依然要能正常運作。

AI 的部分再往下分四層：`LeadService → AIService → LLMProvider → OpenAI SDK`。
最底層刻意做得很薄，它不知道什麼是 Lead、什麼是房仲 ——
所以測試可以直接換成假的，不必花錢也不會因模型隨機性而時紅時綠。

## API

Base path：`/api/v1`

認證（除 `/auth/register`、`/auth/login`、`/health` 外，所有 API 都需要 `Authorization: Bearer <token>`）：

| Method | Path | 說明 |
|---|---|---|
| POST | `/auth/register` | 註冊業務帳號（會自動建立 6 筆範例客戶） |
| POST | `/auth/login` | 登入並取得 access token |
| GET | `/auth/me` | 取得目前登入者，可用於確認 token 是否有效 |

客戶：

| Method | Path | 說明 |
|---|---|---|
| POST | `/leads` | 建立 Lead |
| GET | `/leads` | 列表，可用 `status` / `keyword` / `skip` / `limit` 篩選 |
| GET | `/leads/follow-ups` | 待跟進清單（新進未聯絡 / 到期跟進，兩份分開） |
| GET | `/leads/{id}` | 單筆 Lead（含互動紀錄與計分理由） |
| PATCH | `/leads/{id}` | 部分更新 |
| DELETE | `/leads/{id}` | 刪除 |
| GET | `/health` | 健康檢查 |

AI（會呼叫 OpenAI，沒設 key 時回 503）：

| Method | Path | 說明 |
|---|---|---|
| POST | `/leads/{id}/analyze` | 解析客戶原話，結果寫回需求欄位 |
| POST | `/leads/{id}/follow-up-suggestion` | 產生跟進建議，**不改動客戶的任何欄位** |

互動紀錄（巢狀在 Lead 底下，因為它不會單獨存在）：

| Method | Path | 說明 |
|---|---|---|
| POST | `/leads/{id}/interactions` | 新增互動紀錄 |
| GET | `/leads/{id}/interactions` | 取得 Timeline（由新到舊） |
| DELETE | `/leads/{id}/interactions/{iid}` | 刪除單筆互動紀錄 |

`GET /leads/{id}` 會一併回傳 `interactions`，Lead Detail 頁不必打第二支 API。

**沒有 `/dashboard` 端點**：Dashboard 的數字是前端用 `/leads` 與 `/leads/follow-ups` 算出來的。多開一支只回傳統計值的 API，會多一個「同一件事有兩種算法」的地方，而那兩種算法遲早會不一致。

### 商業規則

- 新增互動紀錄時，若 Lead 仍是 `NEW`，自動推進為 `CONTACTED`
- 但已進展到後續狀態（如 `NEGOTIATING`）的 Lead 不會被退回
- 刪除 Lead 會連帶刪除其所有互動紀錄（cascade）
- Lead Score 由 Rule Engine 算，不交給 LLM；計分理由每次讀取時重算，不存資料庫
- 跟進提醒的天數由業務自己填，系統只給預設值

### 安全性

- 密碼以 bcrypt 雜湊儲存，明文不留存、不出現在任何 API 回應
- 每位業務只看得到自己的客戶，`owner_id` 條件直接寫在 SQL 層
- 存取他人資料一律回 `404` 而非 `403`：回 403 等於承認該 id 存在，
  攻擊者可藉此列舉出系統內的客戶數量
- 登入失敗時，「帳號不存在」與「密碼錯誤」回傳相同訊息，避免帳號枚舉
- 登入失敗的 log 會遮罩 email（`sa***@example.com`）——
  API 回應守住了，log 卻會累積成一份「有人試過的帳號清單」
- `JWT_SECRET` 少於 32 字元時，程式啟動就會直接失敗；
  設定驗證失敗時不會把讀到的值印出來（否則少設一個變數就會讓其餘祕密一起進 log）
- 未預期的例外一律回 500，對外只說一句話 + 一組追查代碼，細節完整進 log

### 出事的時候怎麼查

每個請求都有一組 `request_id`，會寫進每一行 log，也會回寫到回應的
`X-Request-ID` 標頭；5xx 錯誤時前端會把它顯示出來、可一鍵複製。

正式環境沒有終端機，使用者只會說「我剛剛按下去壞掉了」——
有了這組代碼，Render 面板上那幾百行交錯的訊息才拼得回同一次請求。
