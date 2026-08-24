# AI CRM Sales Copilot

AI 驅動的房仲業務 CRM 助手：把客戶的自然語言需求轉成結構化資料，用 Rule Engine 計算 Lead Score，並產生 Follow-up 建議。

完整規劃見 [AI_CRM_Sales_Copilot_開發規劃.md](AI_CRM_Sales_Copilot_開發規劃.md)。

## 目前進度

| Sprint | 內容 | 狀態 |
|---|---|---|
| 0 | Planning（Business Problem / User Story / ERD / API Contract） | ✅ |
| 1 | CRM Core：Lead CRUD + Neon PostgreSQL 連線 | ✅ |
| 1 | CRM Core：Interaction CRUD + Lead Detail Timeline | ✅ |
| 1 | CRM Core：Alembic migration | ✅ |
| 1 | CRM Core：Authentication（JWT + bcrypt） | ⬜ |
| 2 | Vertical Slice + Next.js Frontend | ⬜ |
| 3 | AI Requirement Parsing | ⬜ |
| 4 | AI Evaluation Dataset | ⬜ |
| 5 | Lead Scoring + Follow-up | ⬜ |
| 6 | Testing / Logging / Security | ⬜ |
| 7 | Docker / CI/CD / Deployment | ⬜ |

## 技術選擇

- **Backend**：Python 3.12 + FastAPI + SQLAlchemy 2.0
- **Database**：PostgreSQL 18（Neon, AWS ap-southeast-1 新加坡）
- **Frontend**：Next.js + TypeScript（Sprint 2）
- **AI**：LLM Structured Output + Pydantic 驗證（Sprint 3）

## 後端啟動方式

```bash
cd backend

# 第一次執行才需要
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env          # 再把 DATABASE_URL 填成真實值

# 建立/更新資料表（依 migration）
alembic upgrade head

# 啟動
uvicorn app.main:app --reload
```

啟動後開 <http://127.0.0.1:8000/docs> 看互動式 API 文件。

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
    ├── core/            # 設定、錯誤定義、安全性
    └── db/              # 連線與 Session
```

分層的用意：AI 是 Enhancement，不是地基。即使 LLM API 掛掉，CRM 依然要能正常運作。

## API

Base path：`/api/v1`

| Method | Path | 說明 |
|---|---|---|
| POST | `/leads` | 建立 Lead |
| GET | `/leads` | 列表，可用 `status` / `keyword` / `skip` / `limit` 篩選 |
| GET | `/leads/{id}` | 單筆 Lead |
| PATCH | `/leads/{id}` | 部分更新 |
| DELETE | `/leads/{id}` | 刪除 |
| GET | `/health` | 健康檢查 |

互動紀錄（巢狀在 Lead 底下，因為它不會單獨存在）：

| Method | Path | 說明 |
|---|---|---|
| POST | `/leads/{id}/interactions` | 新增互動紀錄 |
| GET | `/leads/{id}/interactions` | 取得 Timeline（由新到舊） |
| DELETE | `/leads/{id}/interactions/{iid}` | 刪除單筆互動紀錄 |

`GET /leads/{id}` 會一併回傳 `interactions`，Lead Detail 頁不必打第二支 API。

### 商業規則

- 新增互動紀錄時，若 Lead 仍是 `NEW`，自動推進為 `CONTACTED`
- 但已進展到後續狀態（如 `NEGOTIATING`）的 Lead 不會被退回
- 刪除 Lead 會連帶刪除其所有互動紀錄（cascade）

