# AI CRM Sales Copilot 開發規劃

## 1. 專案定位

### 專案名稱
**AI CRM Sales Copilot**

### 專案目標
建立一套 AI 驅動的 CRM 業務助手，協助業務人員：

- 管理潛在客戶 Lead
- 自動解析客戶自然語言需求
- 將非結構化資訊轉換成 CRM 結構化資料
- 計算 Lead Score
- 判斷客戶優先順序
- 產生 Follow-up 建議
- 整理客戶互動紀錄
- 透過 Dashboard 掌握業務狀況
- 後續加入 n8n 自動化
- 後續加入 RAG 知識庫
- 最終加入 AI Copilot / Agent

---

## 2. 專案核心原則

整個專案不應該從「我要使用哪些 AI 技術」開始，而是從：

> 業務工作中有哪些問題值得使用 AI 解決？

核心設計原則：

1. CRM 本身必須先是一個可以正常使用的系統
2. AI 是額外能力，不是整個系統的地基
3. 商業邏輯與 AI 判斷必須分開
4. 可用規則判斷的事情，不應全部交給 LLM
5. 每個 AI 功能都應該有可以驗證效果的方法
6. 不要一開始同時做 RAG、Agent、n8n、Dashboard 等所有功能
7. 採用 Vertical Slice 開發，而不是 Backend 全做完才接 Frontend

---

## 3. 專案解決的商業問題

傳統 CRM 中，業務人員通常需要自行完成：

- 閱讀客戶詢問內容
- 整理客戶需求
- 輸入 CRM
- 判斷客戶購買意願
- 決定跟進優先順序
- 撰寫 Follow-up 訊息
- 查看歷史互動
- 判斷下一步行動

當客戶數量增加時，容易產生：

- 客戶資訊遺漏
- Follow-up 不即時
- 客戶需求整理耗時
- 不知道哪些客戶應優先處理
- CRM 紀錄品質不一致

因此本專案透過：

> CRM + LLM + Rule Engine + Automation + RAG

降低業務在資料整理與客戶追蹤上的時間成本。

---

## 4. 使用情境

第一版主要使用者設定為：

**Sales / 業務人員**

暫時不需要複雜的：

- Admin
- Manager
- HR
- Super Admin
- 多組織權限

避免第一版 Scope 過大。

---

## 5. 使用者流程

```text
客戶提供需求
      ↓
建立 Lead
      ↓
輸入自然語言需求
      ↓
AI 解析客戶需求
      ↓
轉換為結構化資料
      ↓
Lead Scoring Engine
      ↓
判斷 Hot / Warm / Cold Lead
      ↓
AI 產生 Follow-up 建議
      ↓
業務進行聯絡
      ↓
紀錄 Interaction
      ↓
CRM Dashboard
```

未來版本：

```text
客戶表單
    ↓
n8n
    ↓
FastAPI
    ↓
CRM
    ↓
AI Analysis
    ↓
通知業務
```

---

## 6. 系統架構

第一版保持簡單：

```text
             Browser
                │
                ▼
          React / Next.js
                │
             REST API
                │
                ▼
             FastAPI
                │
       ┌────────┼─────────┐
       │        │         │
       ▼        ▼         ▼
 PostgreSQL  AI Service  Scoring Engine
                │
                ▼
               LLM
```

後續：

```text
                 n8n
                  │
                  ▼
               FastAPI
                  │
        ┌─────────┼─────────┐
        ▼         ▼         ▼
   PostgreSQL    LLM       RAG
                            │
                       Vector DB
```

最終：

```text
AI Copilot
    │
    ▼
Tool Calling
    │
    ├── get_leads()
    ├── get_lead()
    ├── get_interactions()
    ├── search_knowledge()
    └── generate_follow_up()
```

---

## 7. 技術選擇

### Frontend

建議：

- React
- Next.js
- TypeScript

如果初期希望降低開發難度，可以先使用：

- HTML
- Bootstrap

但正式作品建議使用 React / Next.js。

### Backend

使用：

**Python + FastAPI**

負責：

- REST API
- Authentication
- Business Logic
- AI Service
- Lead Scoring
- Database 操作

### Database

建議：

**PostgreSQL**

部署時可使用：

- Supabase
- Neon
- Railway PostgreSQL

### AI

可使用：

- OpenAI API
- Gemini API
- Claude API

Backend 應包裝一層 AI Service，不要直接把模型 API 寫死在 Route 裡。

### Automation

後續加入：

**n8n**

主要負責：

- Webhook
- 排程
- Email 通知
- Daily Follow-up
- CRM Workflow Automation

### RAG

後續可以使用：

- pgvector
- Supabase Vector
- Chroma
- Qdrant

視專案需求決定。

---

## 8. MVP 功能範圍

| 功能 | MVP |
|---|---|
| Login | ✅ |
| Lead CRUD | ✅ |
| Interaction CRUD | ✅ |
| Lead Status | ✅ |
| AI Requirement Parsing | ✅ |
| Lead Scoring | ✅ |
| AI Follow-up | ✅ |
| Dashboard | ✅ |
| Logging | ✅ |
| Error Handling | ✅ |
| Testing | ✅ |
| Demo Deployment | ✅ |
| n8n | V2 |
| RAG | V2 |
| AI Copilot | V3 |
| Agent | V3 |
| LINE Integration | V3 |

---

## 9. 正式開發流程

### Phase 0：Business Problem 定義

先明確說明：

> AI CRM Sales Copilot 是一套協助業務自動整理客戶需求、評估客戶優先程度並產生跟進建議的 CRM 系統。

這階段不寫程式。

---

### Phase 1：User Story

建立核心 User Story。

#### Story 01
身為業務，我希望可以建立新的潛在客戶，以便集中管理客戶資訊。

#### Story 02
身為業務，我希望輸入客戶自然語言需求後，AI 能自動整理成 CRM 資料。

#### Story 03
身為業務，我希望可以知道哪些客戶優先程度最高。

#### Story 04
身為業務，我希望 AI 可以根據客戶需求與歷史互動產生 Follow-up 建議。

#### Story 05
身為業務，我希望可以查看客戶過去所有互動紀錄。

---

### Phase 2：Wireframe

在寫程式之前先定義 UI。

第一版頁面：

```text
Login
Dashboard
Leads List
Lead Detail
Create Lead
```

Lead Detail 頁面至少包含：

```text
客戶姓名
狀態
Lead Score
客戶需求
AI Summary
AI Recommendation
Interaction Timeline
新增 Interaction
Generate Follow-up
```

可使用：

- Figma
- Excalidraw
- draw.io

---

### Phase 3：ERD 資料庫設計

#### users

```text
id
name
email
password_hash
created_at
```

#### leads

```text
id
name
phone
email
source
raw_requirement
location
budget_min
budget_max
rooms
parking
purpose
purchase_timeline
status
lead_score
owner_id
created_at
updated_at
```

#### interactions

```text
id
lead_id
type
content
created_at
```

Interaction Type：

```text
CALL
LINE
EMAIL
MEETING
VIEWING
NOTE
```

#### ai_analysis

```text
id
lead_id
summary
intent_level
next_action
follow_up_message
model
prompt_version
created_at
```

保留 `prompt_version`，例如：

```text
lead_analysis_v1
lead_analysis_v2
```

方便未來比較 Prompt 調整後的效果。

---

### Phase 4：API Contract

不要直接開始寫 Backend。

先定義 Frontend 與 Backend 怎麼溝通。

例如：

```text
POST /leads
GET /leads
GET /leads/{id}
PATCH /leads/{id}
DELETE /leads/{id}
```

Interaction：

```text
GET  /leads/{id}/interactions
POST /leads/{id}/interactions
```

AI：

```text
POST /leads/{id}/analyze
POST /leads/{id}/generate-follow-up
```

Dashboard：

```text
GET /dashboard/summary
```

---

### Phase 5：第一條 Vertical Slice

不採用：

```text
Backend 全部完成
↓
Frontend 全部完成
```

而是：

```text
一個功能
Frontend
↓
API
↓
Backend
↓
Database
```

整條先跑通。

第一條：

```text
Create Lead UI
      ↓
POST /leads
      ↓
FastAPI
      ↓
PostgreSQL
      ↓
Lead Detail
```

確認完整流程正常後，再繼續下一個功能。

---

### Phase 6：CRM Core

完成：

- Login
- Lead Create
- Lead Read
- Lead Update
- Lead Delete
- Interaction
- Status
- Dashboard 基礎資料

這個階段完全不需要 AI。

目標：

> 即使 AI API 掛掉，CRM 本身依然可以正常使用。

---

### Phase 7：Backend 分層

建議結構：

```text
backend/

app/

├── main.py
│
├── api/
│   ├── auth.py
│   ├── leads.py
│   ├── interactions.py
│   └── dashboard.py
│
├── models/
│   ├── user.py
│   ├── lead.py
│   └── interaction.py
│
├── schemas/
│   ├── lead.py
│   └── interaction.py
│
├── services/
│   ├── lead_service.py
│   ├── scoring_service.py
│   └── ai_service.py
│
├── repositories/
│   └── lead_repository.py
│
├── core/
│   ├── config.py
│   └── security.py
│
└── db/
    └── database.py
```

避免全部程式放在 `main.py`。

---

### Phase 8：AI Requirement Parsing

使用 LLM 處理非結構化自然語言。

例如：

```text
最近想找七期附近，
預算大概 2000 萬，
三房、有車位，
自己住，
三個月內希望買。
```

AI Structured Output：

```json
{
  "location": "台中七期",
  "budget_max": 20000000,
  "rooms": 3,
  "parking": true,
  "purpose": "自住",
  "purchase_timeline_months": 3
}
```

必須使用：

- Structured Output
- JSON Schema
- Pydantic Validation

避免 LLM 自由輸出。

---

### Phase 9：AI Service

不要直接在 API Route 呼叫 LLM。

建立：

```text
AIService
```

例如：

```python
analyze_lead()
generate_follow_up()
summarize_interactions()
```

架構：

```text
API
 ↓
AI Service
 ↓
LLM Provider
```

未來即使替換 OpenAI、Gemini、Claude 或 Local LLM，其他程式也不需要大幅修改。

---

### Phase 10：AI Evaluation Dataset

建立：

```text
tests/evaluation_dataset.json
```

準備約：

**30～100 筆模擬客戶需求**

例如：

```text
我想找西屯三房，
預算大概2000萬，
有車位，
希望三個月內買。
```

人工 Ground Truth：

```json
{
  "location": "西屯",
  "rooms": 3,
  "budget_max": 20000000,
  "parking": true,
  "timeline_months": 3
}
```

最後可以呈現：

```text
AI Requirement Extraction Evaluation

Location Accuracy: 98%
Budget Accuracy: 96%
Rooms Accuracy: 100%
Timeline Accuracy: 87%
```

---

### Phase 11：Lead Scoring Engine

Lead Score 不應由 LLM 自由判斷。

使用 Rule Engine。

例如：

```text
預算明確        +15
區域明確        +10
房型明確        +10
3 個月內購買    +20
提供電話        +10
已有自備款      +15
需求模糊        -10
```

輸出：

```json
{
  "score": 85,
  "level": "HOT",
  "reasons": [
    "購屋時間明確",
    "預算明確",
    "已提供聯絡方式"
  ]
}
```

分級：

```text
80～100 → Hot Lead
60～79 → Warm Lead
0～59 → Cold Lead
```

這樣可以確保：

> 相同資料永遠得到相同 Score。

---

### Phase 12：AI Follow-up Recommendation

輸入：

```text
Lead Information
+
Lead Score
+
Interaction History
```

AI 產生：

```text
Recommended Action
Recommended Message
```

例如：

```text
建議 24 小時內電話聯繫，
確認客戶目前是否仍以七期三房為主要需求。
```

---

### Phase 13：Follow-up Evaluation

生成式文字沒有唯一答案，因此不採 Exact Match。

建立 Criteria：

```text
✓ 是否根據客戶需求回答
✓ 是否使用 Interaction History
✓ 是否建議合理的下一步
✓ 是否避免捏造不存在資訊
✓ 是否避免宣稱客戶已做出不存在的決定
✓ 語氣是否合理
```

---

### Phase 14：Dashboard

第一版至少顯示：

```text
Total Leads
Hot Leads
Warm Leads
Need Follow-up
Conversion Rate
Average Lead Score
```

以及 Lead Funnel：

```text
New
 ↓
Contacted
 ↓
Interested
 ↓
Meeting
 ↓
Negotiating
 ↓
Won
```

---

### Phase 15：Error Handling

AI API 失敗不能讓整個 CRM 失效。

例如：

```text
建立 Lead
✅ 成功

AI Analysis
❌ 失敗
```

UI 顯示：

```text
AI 分析目前無法完成，
請稍後重新嘗試。
```

並提供：

```text
Retry Analysis
```

確保：

> AI 是 Enhancement，不是 Single Point of Failure。

---

### Phase 16：Logging

至少紀錄：

```text
Lead created
Lead updated
AI analysis started
AI analysis completed
AI API timeout
Database error
```

使用 Python `logging`。

---

### Phase 17：Testing

#### Unit Test

主要測試：

- Lead Scoring
- Parsing Validation
- Business Rules

#### API Test

測試：

- POST /leads
- GET /leads
- PATCH /leads
- POST /interactions

#### AI Evaluation

測試：

- Location Extraction
- Budget Extraction
- Room Extraction
- Timeline Extraction
- Follow-up Quality

---

### Phase 18：Security

`.env` 管理：

```text
DATABASE_URL
OPENAI_API_KEY
JWT_SECRET
```

不能將 API Key 放到 GitHub。

密碼必須 Hash，例如使用 bcrypt。

Demo 資料全部使用虛構客戶資料。

---

### Phase 19：Docker —— **決定不做**

原本規劃 `Dockerfile` + `docker-compose.yml`（frontend / backend / postgres）。
實際評估之後拿掉了，理由是**這個專案的每一個預設用途都不成立**：

| Docker 常見的用途 | 在這個專案 |
|---|---|
| 部署到雲端 | 用不到。Render 支援直接跑 Python，Vercel 跑 Next.js 完全不碰 Docker |
| 本機起完整環境（含資料庫） | 用不到。資料庫在 Neon 雲端，本機不需要跑 Postgres 容器 |
| 環境一致性 | 用不到。單人開發，一台機器 |
| CI 環境 | 用不到。GitHub Actions 用 `setup-python` 更快 |

剩下唯一的理由是**求職訊號**（Docker 常出現在後端職缺的 JD 上）。
那個理由本身不假，但它換不到這個代價：

**第一次部署時，未知數要越少越好。** 用 Docker 部署失敗時，
分不清是 Dockerfile 寫錯、環境變數沒設對、還是程式本身的問題 ——
三個變數同時未知，查起來會非常痛苦。

**而且沒在用的 Dockerfile 會腐爛。** 改了依賴、換了 Python 版本之後它會悄悄壞掉，
面試官真的 `docker build` 而它失敗，比沒有 Dockerfile 糟糕得多 ——
那證明的是「放了一個自己沒在用的東西」。

> 這件事本身是可以在面試講的內容：知道 Docker 在什麼情況下**才真的必要**
> （多人協作、需要本機起依賴服務、部署目標不提供 runtime），
> 比在不需要的地方放一個，更能說明判斷力。

日後若真的需要（例如換到不提供 Python runtime 的部署平台），
再補上並**實際用它部署**，不要只是放著。

---

### Phase 20：CI/CD

GitHub Actions：

```text
Push
 ↓
Run Tests
 ↓
Build
```

後續：

```text
main
 ↓
Test
 ↓
Build
 ↓
Deploy
```

---

### Phase 21：部署 MVP

Frontend：

```text
Vercel
```

Backend 可選：

```text
Render
Railway
Fly.io
```

Database：

```text
Supabase
Neon
Railway PostgreSQL
```

第一版不需要 Kubernetes。

作品目的：

> 穩定、可以 Demo。

---

### Phase 22：n8n Automation

MVP 穩定後再加入。

例如：

```text
客戶 Web Form
       ↓
      n8n
       ↓
Create Lead API
       ↓
AI Analyze
       ↓
Lead Score
       ↓
通知業務
```

每天：

```text
09:00
 ↓
n8n Schedule
 ↓
讀取 CRM API
 ↓
找出需要 Follow-up 客戶
 ↓
產生今日待辦
 ↓
Email 通知
```

n8n 不建議直接寫 PostgreSQL。

建議：

```text
n8n
 ↓
FastAPI
 ↓
PostgreSQL
```

所有 Business Logic 統一經過 Backend。

---

### Phase 23：RAG Knowledge Base

因為作品沒有真正公司內部資料，可以建立：

**虛構公司的 Domain Knowledge Base**

例如：

```text
knowledge_base/

├── company/
│   ├── sales_sop.md
│   ├── customer_followup_policy.md
│   └── lead_management_rule.md
│
├── properties/
│   ├── property_A.md
│   ├── property_B.md
│   └── property_C.md
│
├── faq/
│   ├── mortgage_faq.md
│   ├── viewing_faq.md
│   └── contract_faq.md
│
└── scripts/
    ├── hot_lead_script.md
    └── cold_lead_script.md
```

RAG 流程：

```text
Documents
   ↓
Chunking
   ↓
Embedding
   ↓
Vector DB
   ↓
Retrieval
   ↓
LLM
   ↓
Answer + Source
```

---

### Phase 24：RAG Demo 設計

刻意設計有辨識難度的資料，例如：

```text
A
2000萬
3房
沒有車位

B
2100萬
3房
有車位

C
1900萬
2房
有車位
```

詢問：

```text
預算2000萬內，
三房，
一定要有車位，
有哪些符合？
```

正確答案：

```text
目前沒有完全符合條件的物件。
```

藉此展示：

- Retrieval Accuracy
- Context Understanding
- Hallucination Control

---

### Phase 25：AI Copilot

RAG、CRM、Scoring 都穩定後再加入。

例如：

```text
今天最值得聯絡哪些客戶？
```

Backend：

```text
Database Query
     ↓
Scoring
     ↓
Business Rules
     ↓
LLM Summary
```

第一版 Copilot 不需要真正 Agent。

---

### Phase 26：Tool Calling Agent

最後再將穩定功能包成 Tools。

例如：

```text
get_leads()
get_lead()
get_interactions()
search_knowledge()
generate_follow_up()
```

Agent 是最後的：

> Orchestration Layer

而不是第一版系統的核心。

---

## 10. Sprint 開發規劃

### Sprint 0：Planning

完成：

```text
Business Problem
User Story
MVP Scope
Wireframe
Architecture
ERD
API Contract
```

### Sprint 1：CRM Core

完成：

```text
FastAPI
PostgreSQL
Authentication
Lead CRUD
Interaction CRUD
```

### Sprint 2：Vertical Slice + Frontend

完成：

```text
Login
Lead List
Create Lead
Lead Detail
Interaction
Dashboard
```

確保：

```text
Frontend
 ↓
API
 ↓
Backend
 ↓
Database
```

整條流程正常。

### Sprint 3：AI Integration

完成：

```text
Requirement Parsing
Structured Output
Pydantic Validation
AI Summary
```

### Sprint 4：AI Evaluation

完成：

```text
Evaluation Dataset
Ground Truth
Parsing Accuracy
Error Analysis
```

### Sprint 5：Sales Intelligence

完成：

```text
Lead Scoring
Score Reasons
Follow-up Recommendation
Follow-up Evaluation
```

### Sprint 6：Quality

完成：

```text
Unit Test
API Test
Logging
Error Handling
Security
```

### Sprint 7：Deployment

完成：

```text
GitHub Actions
Production Database
Frontend Deploy      Vercel
Backend Deploy       Render（直接跑 Python，不用 Docker，理由見 Phase 19）
```

到這個階段：

> 第一版正式完成，可以開始放履歷與作品網站。

### Sprint 8：Automation

加入：

```text
n8n
Webhook
Daily Follow-up
Email Notification
```

### Sprint 9：RAG

加入：

```text
Knowledge Base
Chunking
Embedding
Vector DB
Retrieval
Citation
RAG Evaluation
```

### Sprint 10：AI Copilot

加入：

```text
CRM Natural Language Query
Customer Summary
Today's Priority Leads
```

### Sprint 11：Agent

最後加入：

```text
Tool Calling
Agent Orchestration
CRM Tools
RAG Tools
```

---

## 11. Git 開發流程

Branch：

```text
main
develop
feature/lead-crud
feature/interaction
feature/ai-analysis
feature/lead-scoring
feature/dashboard
feature/rag
```

流程：

```text
feature branch
      ↓
Pull Request
      ↓
develop
      ↓
Test
      ↓
main
```

即使是個人專案，也可以模擬正式團隊 Workflow。

---

## 12. Git Commit 規範

避免：

```text
update
fix
test
123
```

建議：

```text
feat: add lead creation API
feat: implement AI lead analysis
feat: implement lead scoring service
fix: handle AI API timeout
test: add lead scoring unit tests
refactor: separate AI service from lead service
docs: update system architecture
```

---

## 13. README 規劃

GitHub README 建議：

```text
# AI CRM Sales Copilot

## Project Overview
## Business Problem
## Solution
## Live Demo
## Demo Video
## Features
## System Architecture
## AI Workflow
## Lead Scoring
## AI Evaluation
## RAG
## Database Schema
## API Documentation
## n8n Workflow
## Tech Stack
## Testing
## Deployment
## Screenshots
## Future Improvements
```

---

## 14. Demo 設計

Demo 不應要求面試官：

```text
註冊
↓
Email 驗證
↓
建立公司
↓
新增資料
↓
才可以操作
```

建議提供：

```text
Try Demo
```

直接進入。

預先建立：

```text
30～50 筆虛構 Lead
Hot Lead
Warm Lead
Cold Lead
不同 Interaction
不同 Status
```

---

## 15. Demo 核心流程

Demo 時輸入：

```text
我最近想找西屯三房，
預算大概2000萬，
希望有車位，
自住，
最好三個月內買。
```

AI：

```text
Location：西屯
Budget：2000萬
Rooms：3
Parking：Yes
Purpose：自住
Timeline：3個月
```

Lead Scoring：

```text
Lead Score：85
HOT Lead
```

Reasons：

```text
+ 預算明確
+ 區域明確
+ 房型明確
+ 購屋時間明確
```

AI Follow-up：

```text
建議24小時內聯絡客戶，
確認目前是否已開始看房，
並提供符合西屯、三房、有車位條件的物件。
```

---

## 16. 如何證明 AI 不是亂回答

Demo 中可以加入：

### AI Evaluation

```text
Requirement Extraction Accuracy

Location：98%
Budget：96%
Rooms：100%
Timeline：87%
```

並說明：

> 使用人工建立的 Evaluation Dataset，比較 AI Structured Output 與 Ground Truth。

Lead Score：

> 使用 deterministic Rule Engine，不由 LLM 自由決定。

Follow-up：

> 使用 Criteria-based Evaluation 評估合理性、Context 使用與 Hallucination。

---

## 17. 個人網站呈現

個人網站：

```text
Home
About Me
Skills
Projects
Resume
Contact
```

Projects：

```text
AI CRM Sales Copilot
```

專案頁：

```text
AI CRM Sales Copilot

[Live Demo]
[GitHub]
[Demo Video]

Problem
Solution
Demo
Architecture
AI Evaluation
Technical Details
Future Roadmap
```

---

## 18. 履歷呈現方式

### AI CRM Sales Copilot｜個人專案

建立 AI 驅動 CRM 業務助手，整合 FastAPI、PostgreSQL、LLM 與自動化 Workflow，將客戶自然語言需求轉換為結構化 CRM 資料，並透過 Rule-based Lead Scoring 評估客戶優先程度及產生 Follow-up 建議。

主要實作：

- 建立 RESTful CRM Backend API
- 建立 PostgreSQL 客戶與互動紀錄資料模型
- 使用 LLM Structured Output 解析自然語言客戶需求
- 建立 Rule-based Lead Scoring Engine
- 建立 AI Follow-up Recommendation
- 建立 AI Evaluation Dataset 驗證抽取效果
- 建立 CRM Dashboard
- 建立 CI/CD Pipeline
- 後續加入 n8n Automation
- 後續加入 RAG Knowledge Base
- 後續加入 AI Copilot / Tool Calling Agent

---

## 19. 最終開發優先順序

```text
Business Problem
        ↓
User Story
        ↓
MVP Scope
        ↓
Wireframe
        ↓
ERD
        ↓
API Contract
        ↓
Vertical Slice
        ↓
CRM Core
        ↓
AI Parsing
        ↓
AI Evaluation
        ↓
Lead Scoring
        ↓
Follow-up Recommendation
        ↓
Dashboard
        ↓
Testing
        ↓
Error Handling
        ↓
Deployment
────────────────────
MVP 完成，可開始投履歷
────────────────────
        ↓
n8n
        ↓
RAG
        ↓
RAG Evaluation
        ↓
AI Copilot
        ↓
Tool Calling Agent
```

---

## 20. 最終結論

這個專案的重點不是：

> 使用越多 AI 技術越好。

而是：

> 能否建立一套真正可以使用、可以驗證、可以 Demo 的 AI 系統。

整體開發思想：

```text
CRM 是核心
FastAPI 負責 Business Logic
PostgreSQL 負責資料
LLM 處理非結構化資訊
Rule Engine 處理可確定的商業規則
Evaluation 驗證 AI 效果
n8n 處理 Workflow Automation
RAG 提供企業知識
Agent 最後負責 Orchestration
```

最重要的開發原則：

> 不要先做 Agent，再想 Agent 可以做什麼。

而應該先把：

```text
CRM
AI Parsing
Scoring
Follow-up
RAG
```

每個能力做好並驗證。

最後才將這些能力組合成 Agent。

這樣做出來的 AI CRM Sales Copilot，才不會只是一個 ChatGPT Demo，而會是一個具有：

- 軟體工程能力
- Backend 開發能力
- API 設計能力
- Database 設計能力
- AI Integration 能力
- AI Evaluation 能力
- Automation 能力
- RAG 能力
- System Design 能力

的完整 AI 求職作品。
