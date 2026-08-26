# 開發進度與後續規劃

> 最後更新：2026-08-26
>
> 這份文件記錄「做到哪裡」與「為什麼這樣做」。
> 操作指令請看 [README.md](../README.md)，完整構想請看 [開發規劃書](../AI_CRM_Sales_Copilot_開發規劃.md)。

---

## 一、目前進度

| Sprint | 內容 | 狀態 |
|---|---|---|
| 0 | Planning：Business Problem / User Story / ERD / API Contract | ✅ |
| 1 | CRM Core：Lead & Interaction CRUD、Auth、Alembic | ✅ |
| 2 | Vertical Slice：Next.js 前端，前端到資料庫全鏈路跑通 | ✅ |
| 3 | AI Requirement Parsing | ✅ |
| 4 | AI Evaluation Dataset | ✅ |
| 5 | Lead Scoring + Follow-up | 🔄 Scoring 與 Need Follow-up 完成，AI 建議未做 |
| 6 | Quality：Testing / Logging / Error Handling / Security | ⬜ |
| 7 | Deployment：Docker / CI/CD / 上線 | ⬜ **← MVP 完成，可開始投履歷** |
| 8 | n8n Automation | ⬜ |
| 9 | RAG Knowledge Base | ⬜ |
| 10 | AI Copilot | ⬜ |
| 11 | Tool Calling Agent | ⬜ |

### Sprint 1 完成內容

- FastAPI 分層架構：`api / services / repositories / models / schemas / core / db`
- Lead CRUD，支援 status 篩選與姓名/電話關鍵字搜尋
- Interaction CRUD，巢狀於 Lead 之下，Timeline 由新到舊
- Authentication：JWT + bcrypt，每位業務只看得到自己的客戶
- Alembic migration 管理 schema
- 後端 65 個測試

### Sprint 2 完成內容

- Next.js 16 + React 19 + TypeScript + Tailwind v4 + shadcn/ui
- TanStack Query（快取與重新驗證）+ react-hook-form + zod
- 頁面：登入、註冊、客戶列表、新增客戶、客戶詳細頁
- 前端型別由後端 OpenAPI schema 自動生成，不手寫

### Sprint 3 完成內容

- 新增 `budget_is_approximate` / `property_type` / `building_age_max` 三個欄位與 `ai_analysis` 表
- 四層分工：`LeadService → AIService → LLMProvider → OpenAI SDK`
- OpenAI Structured Output（strict JSON Schema）+ Pydantic 二次驗證
- `POST /leads/{id}/analyze`：同步等待約 1～4 秒
- 前端：「AI 解析」按鈕、loading、失敗就地重試、欄位上的 `AI` 徽章
- 後端測試 85 個（新增 20 個，全部用假 provider，不呼叫真實 OpenAI）

### Sprint 4 完成內容

- 開發集 40 筆 + **held-out 驗證集 21 筆**，Ground Truth 全人工標註
- 評估腳本可切換模型與 prompt 版本，逐欄位計算正確率、Recall、Precision、捏造率
- Error Analysis 指出 v1 的錯誤 78% 集中在 `location` → 據此寫出 prompt v2
- **驗證集成績：欄位正確率 99.6%、完全正確率 95.2%、捏造率 0%**（v4，11 個欄位）
- 模型比較結論：gpt-5.4-mini 是甜蜜點，換 gpt-5.4 買不到準確率
- 完整結果見 [docs/evaluation/README.md](evaluation/README.md)
- 後端測試 106 個

### Sprint 5 進行中

已完成：

- 新增 `urgency` 欄位（AI 判斷急迫語氣），prompt v3 → v4
- `ScoringService`：deterministic Rule Engine，滿分 100，逐條列出計分理由
- Need Follow-up：兩份分開的清單（新進未聯絡 / 到期跟進）+ 靜音機制
- Dashboard：客戶總數、意願分佈、待跟進、成交率、銷售漏斗
- 前端：計分理由卡片、下次提醒快捷鈕、列表靜音標示
- 後端測試 156 個

未完成：AI Follow-up 建議、Follow-up Evaluation

### 環境現況

| 項目 | 狀態 |
|---|---|
| 資料庫 | Neon PostgreSQL 18，AWS ap-southeast-1（新加坡） |
| GitHub | `github.com/ian0629082/AI_CRM_Sales_Copilot` |
| 分支 | `main` / `develop` / `feature/*`，皆已推送 |
| OpenAI API Key | 已填入 `backend/.env` |
| LLM 型號 | `gpt-5.4-mini`（環境變數 `OPENAI_MODEL`，換型號不必改程式碼） |
| Prompt 版本 | `lead_analysis_v4`（v1～v3 全部保留在程式碼中，供評估比較用） |
| Docker | 尚未安裝（Sprint 7 才需要） |
| Demo 帳號 | `demo@example.com` / `demo1234`，Neon 上有測試資料 |

---

## 二、已定案的設計決策

記錄「為什麼」，避免日後回頭看程式碼時想不起原因，也是面試時要能說明的內容。

### 架構層面

**AI 是 Enhancement，不是地基。**
Sprint 1、2 完全沒有 AI 也能正常運作的 CRM。即使 LLM API 全掛，客戶資料的增刪改查、互動紀錄、登入都不受影響。

**Model 與 Schema 分開。**
Model 是資料庫的樣子，Schema 是 API 對外的承諾。改資料庫欄位不會直接打爛前端。

**商業邏輯集中在 Service 層。**
API route 只負責收發 HTTP，Repository 只負責讀寫資料庫。日後 n8n（Sprint 8）與 Agent（Sprint 11）也要新增客戶與互動，共用同一套規則，不必抄第二遍。

**Service 不知道 HTTP 存在。**
它丟 `NotFoundError`，由 `main.py` 的 exception handler 翻譯成 404。

### 安全層面

**存取他人資料回 404 而非 403。**
回 403 等於承認「這個 id 存在，只是不給你看」，攻擊者可藉此列舉出系統內的客戶數量。

**`owner_id` 過濾寫在 SQL 層，不是撈回來再比對。**
Repository 的每個查詢都強制帶 `owner_id` 條件，少一個漏檢的機會。授權綁在 API 的 service dependency 上，而非每支 route 各寫一次。

**登入失敗訊息刻意一致。**
「帳號不存在」與「密碼錯誤」回傳相同訊息，避免帳號枚舉。

**`get_current_user` 仍要查一次資料庫。**
token 簽章有效不代表帳號還在，只驗簽章是不夠的。

### 依賴選擇

**用 bcrypt 而非 passlib。**
規劃書原本寫 `passlib[bcrypt]`，但 passlib 1.7.4 自 2020 年未更新，讀不到 bcrypt 5.x 的版號，連 hash 都會失敗。

**用 PyJWT 而非 python-jose。**
後者自 2021 年未更新，其依賴 ecdsa 有已知的 timing attack 弱點（CVE-2024-23342）。FastAPI 官方文件現也改用 PyJWT。

### 評估層面（Sprint 4）

**資料集分成開發集與 held-out 驗證集。**
v2 的 prompt 是看著 v1 在開發集上的錯誤寫出來的，它在開發集拿 100% 沒有意義——
等於對著考卷改答案。只有從未參與調校的驗證集，數字才能對外引用。
兩份分數的落差（開發集 +20 個百分點 vs 驗證集 +9.5 個）本身就是過擬合程度的估計值。

**資料集不用 LLM 生成。**
若用同一個模型出題又拿它作答，量到的是自我一致性，不是準確率。

**捏造與漏抽要分開統計。**
「客戶沒提到預算，模型生了一個 2000 萬」跟「客戶說 2000 萬，模型抽成 200 萬」
是兩種不同的問題，混在一起看就不知道該修 prompt 的哪一段。
捏造是最不能妥協的指標——CRM 裡出現客戶從沒說過的資訊，比欄位空著嚴重得多。

**評估程式本身要有單元測試。**
一份算錯的準確率比沒有準確率更糟，它會讓人對著錯的方向調 prompt，
而且錯得很難察覺——沒有人會懷疑 87.3% 是算錯的。

### Scoring 與跟進（Sprint 5）

**Lead Score 只看客戶本身，不看業務做了多少事。**
一度把「帶看過」算進分數，後來拿掉：那對新客戶不公平——
剛填完表單的客戶不管條件多好，那幾分都是結構性拿不到的。
一個拿不到滿分的族群跟一個拿得到的族群，分數就不能互相比較，
而不能比較的分數拿來排序是危險的。
拿掉之後，剛進來、需求清楚又很急的客戶可以拿到 100 分，正是該立刻打電話的那種人。

**計分理由不存資料庫，每次讀取時重算。**
規則是確定性的，同樣的資料一定得到同樣的理由，存起來只會多一份可能過期的副本。
理由加總必須等於分數，有測試守著——「可解釋」不是加分項，
是這個分數敢拿來排序的前提。

**跟進提醒由業務填，系統只給預設值。**
原本寫了一整張規則表（議價 2 天、帶看 1 天、說不急 14 天，還有優先順序），
後來整張丟掉。業務知道的比規則多：客戶說「我下週三再回你」，
業務填 7 天就對了，規則猜不到那句話。
規則因此降級成「建議的預設值」，業務隨時可以覆蓋。

**備註預設隔天再提醒。**
「備註」是個大雜燴——可能是「致電未接」，也可能是「客戶說下週回覆」。
系統分不出來，所以往保守的方向猜：假設還沒聯絡上。
漏掉一個沒接通的客戶，代價比多提醒一次大得多。

**待跟進分兩堆，靜音只給數字。**
「新進未聯絡」與「到期跟進」對應兩種不同的業務動作，混在一起就分不出
哪些是還沒認識、哪些是快跑掉了。
靜音的客戶不列在清單裡——一份會冒出你關過的人的待辦清單，沒有人敢信；
但要給個數字，不然業務會納悶那個客戶怎麼消失了。

### 前端層面

**JWT 存 localStorage，不用 httpOnly cookie。**
前端將部署在 Vercel、後端在 Render，屬於不同網域。跨網域 cookie 需要 `SameSite=None`，會被現代瀏覽器的第三方 cookie 限制擋掉。代價是可被 XSS 讀取；正式產品會把前端與 API 收在同一網域下（BFF 或反向代理）再改用 cookie。

**前端型別由後端 OpenAPI 生成。**
後端改了欄位，前端 `npm run build` 就會編譯失敗 —— 這正是要的效果，而不是等到 Demo 時才發現畫面空白。

---

## 三、Sprint 3 設計決議（已實作）

### 分層

```
API route          POST /leads/{id}/analyze
      ↓
LeadService        決定「要不要分析、分析完怎麼處理」
      ↓
AIService          決定「用什麼 prompt、怎麼驗證結果」
      ↓
LLMProvider        只負責「把字串送給 OpenAI 拿回字串」
      ↓
OpenAI SDK
```

最底層的 `LLMProvider` 刻意做得很薄，它不知道什麼是 Lead、什麼是房仲。
這樣測試時可以直接換成假的 provider，不必花錢也不會因模型隨機性而時紅時綠。

### 三個已定案的選擇

| 決策 | 選擇 |
|---|---|
| 解析結果如何進入 CRM | **直接寫入 lead 欄位**，畫面標示「AI 解析」徽章且可手動修改 |
| 執行方式 | **同步等待**（2～5 秒，前端顯示 loading） |
| `ai_analysis` 表 | **一次建齊全部欄位**，Sprint 5 的 Follow-up 不必再跑 migration |

### AI 要抽取的 10 個欄位

| 欄位 | 說明 | 狀態 |
|---|---|---|
| `location` | 區域 | 已有 |
| `budget_min` / `budget_max` | 預算 | 已有 |
| `budget_is_approximate` | 客戶說的是概數還是精確數字 | **待新增** |
| `rooms` | 幾房（整數） | 已有 |
| `property_type` | 房屋類型（六類） | **待新增** |
| `building_age_max` | 屋齡上限（年） | **待新增** |
| `parking` | 車位 | 已有 |
| `purpose` | 購屋目的 | 已有 |
| `purchase_timeline` | 時程（月） | 已有 |

`property_type` 六類：電梯大樓、華廈、公寓、透天厝、別墅、套房。

### 抽取規則（同時是 Sprint 4 的 Ground Truth 標準）

同一句話該解析成什麼必須有明確約定，否則 Sprint 4 算準確率時會變成
「AI 和我對答案的想法不一樣」，而不是「AI 錯了」。

| 客戶說法 | 解析結果 | 理由 |
|---|---|---|
| 「預算 2000 萬」 | `budget_max: 20000000`<br>`budget_is_approximate: false` | 房仲情境下客戶講預算幾乎都指上限 |
| 「1500 到 2000 萬」 | `budget_min: 15000000`<br>`budget_max: 20000000` | 明確區間才填兩端 |
| 「2000 萬左右」 | `budget_max: 20000000`<br>`budget_is_approximate: true` | 不自行推算區間 |
| 「三房」 | `rooms: 3` | |
| 「三、四房都可以」 | `rooms: 3` | 取下限，符合業務先從門檻找起的實務 |
| 「三個月內」 | `purchase_timeline: 3` | 單位是月 |
| 「不急」「明年再說」 | `purchase_timeline: null` | 不猜數字，沒說就是沒說 |
| 「有車位最好」 | `parking: true` | 有提到需求就算 |
| 「屋齡 10 年內」 | `building_age_max: 10` | |
| 「新成屋」「中古屋」 | `building_age_max: null` | 沒有數字就不推算年數 |
| 「七期」 | `location: "七期"` | 保留客戶原話，不自行補成「台中七期」 |
| 完全沒提到的欄位 | `null` | |

最關鍵的兩條原則是 **不推算** 與 **不補全**。
規劃書 Phase 13 明確要求「避免捏造不存在資訊」—— AI 把「2000 萬左右」變成一個精確區間，
看起來聰明，實際上是在製造客戶從沒說過的資訊。

### 預算緩衝規則（Rule Engine 負責，不是 AI）

客戶說「2000 萬左右」時，搜尋若只找到 2000 萬以內的物件，會漏掉 2000～2100 萬之間的選擇。
因此需要往上加緩衝，但**這個計算由 Rule Engine 執行，不交給 LLM**：

```
資料庫存                      搜尋時計算
  budget_max: 20000000    →    effective_max = budget_max × 1.05
  budget_is_approximate: true
```

**為什麼用 5% 而不是固定 100 萬**：模糊詞的容忍度是等比例的。
客戶說「1000 萬左右」心裡的彈性約 50 萬，說「5000 萬左右」時彈性不會只有 100 萬。

**為什麼不讓 AI 直接輸出 21000000**：

1. LLM 做算術不可靠，而且規則越多 prompt 越長、抽取錯誤率越高
2. Sprint 4 的 Evaluation 會分不清「模型理解錯誤」與「規則沒套用」
3. 「預算 2000 萬不能超過」與「2000 萬左右」意思不同，前者不該加緩衝。
   若 AI 直接吐 21000000，這兩種情況在資料庫裡就無法區分

`budget_is_approximate` 在 **Sprint 5 的 Lead Scoring 立刻會用到**：
規劃書的計分規則有「預算明確 +15」，說「2000 萬左右」的客戶通常還在觀望，
與說「就是 2000 萬」的客戶購買意願有差，這個欄位讓 Scoring Engine 能分辨。

### 其他實作要點

- **Structured Output 不等於「叫 AI 回 JSON」**：OpenAI 的 strict schema 在解碼層面約束輸出，
  與在 prompt 裡寫「請回傳 JSON」是不同的可靠度等級
- **Pydantic 驗證不是多餘的第二道關卡**：strict 模式傳不了數值範圍等約束，
  schema 保證「結構正確」，Pydantic 保證「值合理」（預算不能是負數、房數不能是 99）
- **`raw_requirement` 永遠不被覆蓋**：客戶原話是唯一事實來源，Prompt 改版後要能重跑歷史資料
- **`prompt_version` 要存**：例如 `lead_analysis_v1`，方便比較 Prompt 調整後的效果
- **模型型號寫成環境變數 `OPENAI_MODEL`**：換模型不必改程式碼，
  Sprint 4 可直接跑兩個模型比較準確率與成本
- **AI 失敗不能讓 CRM 失效**：分析失敗時 Lead 本身不受影響，
  前端顯示「AI 分析目前無法完成」加重試按鈕
- **單元測試不呼叫真實 OpenAI**：把 `LLMProvider` 換成假的回傳固定 JSON。
  測「AI 準不準」是 Sprint 4 Evaluation 的職責，用另一套機制

### 實作時多出來的兩個決定

原本的設計沒討論到，但寫下去才發現非決定不可：

**AI 只填、不清空。**
AI 回 `null` 代表「客戶沒提到」，不代表「業務填錯了」。
若讓 `null` 覆蓋業務手動輸入的內容，按一次「AI 解析」就會清掉自己剛填好的資料——
那是會讓人再也不敢按第二顆按鈕的行為。要清空欄位請用一般編輯功能，那是明確的意圖表達。

**「AI 徽章」用比對而不是旗標。**
畫面上的 `AI` 徽章，是拿 lead 現值跟 `ai_analysis.parsed_result` 比對得出的，
不是另外存一個「這欄是 AI 填的」布林值。
好處是業務手動改過之後徽章會自動消失——值已經不是 AI 給的了，還掛著徽章就是在騙人。

**`budget_is_approximate` 不開放在新增客戶時填。**
它回答的是「客戶說預算時的語氣」，這件事只有讀過原話才知道，
所以由 AI 解析填入，或事後用 PATCH 修改。

---

## 四、後續 Sprint 規劃

### Sprint 5 剩下的部分

1. AI Follow-up Recommendation：依 Lead 資料 + Score + 互動歷史產生建議
2. Follow-up Evaluation：Criteria-based（是否使用互動歷史、是否捏造資訊、語氣是否合理）

### Sprint 6：Quality

Unit Test（Scoring 規則、驗證邏輯）、API Test、Logging、Error Handling、Security 檢查。

### Sprint 7：Deployment ← MVP 完成

Docker + docker-compose、GitHub Actions CI、前端上 Vercel、後端上 Render/Railway。
Demo 要能「Try Demo」一鍵進入，預先建立 30～50 筆虛構客戶。

**到這裡第一版正式完成，可以開始投履歷。**

### Sprint 8～11：加分項

| Sprint | 內容 |
|---|---|
| 8 | n8n Automation：Webhook 建立客戶、每日 09:00 產生待辦並寄信 |
| 9 | RAG：虛構公司知識庫、Chunking、Embedding、Vector DB、Citation |
| 10 | AI Copilot：自然語言查詢 CRM、「今天最值得聯絡哪些客戶」 |
| 11 | Tool Calling Agent：把穩定功能包成 Tools，Agent 作為 Orchestration Layer |

> 規劃書的核心提醒：**不要先做 Agent，再想 Agent 可以做什麼。**
> 先把 CRM、AI Parsing、Scoring、Follow-up、RAG 每個能力做好並驗證，最後才組合成 Agent。

---

## 五、開發流程約定

### Git 分支

```
main        只放穩定、可展示的版本
develop     開發中的整合分支
feature/*   每個功能自己的分支
```

流程：`feature/xxx` →（測試通過）→ `develop` →（Sprint 完成）→ `main` → push

合併一律用 `--no-ff` 保留分支歷史，合併後必須重跑測試才進下一步。

### Commit 訊息

用 `feat:` / `fix:` / `chore:` / `docs:` / `test:` / `refactor:` 前綴，
說明「為什麼」而不只是「改了什麼」。面試官點進 GitHub，commit history 是第一眼看到的東西。

### 改 schema 的固定流程

```bash
cd backend
# 1. 改 model
# 2. 產生 migration（產生後一定要打開看內容，autogenerate 不是永遠正確）
alembic revision --autogenerate -m "add xxx"
# 3. 套用
alembic upgrade head
```

### 改後端 schema 後要同步前端型別

```bash
cd backend  && python -m scripts.export_openapi
cd frontend && npm run gen:api
```

---

## 六、下一步

Sprint 5：Lead Scoring + Follow-up Recommendation。

第一個動作是 `ScoringService`——**deterministic Rule Engine，不由 LLM 決定分數**。
`budget_is_approximate` 在這裡會第一次派上用場：說「2000 萬左右」的客戶
通常還在觀望，與說「就是 2000 萬」的購買意願有差。

建議在 `feature/lead-scoring` 分支上進行。
