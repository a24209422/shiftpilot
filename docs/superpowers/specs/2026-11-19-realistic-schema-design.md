# 設計：讓 text2sql 面對接近真實的資料庫結構

日期：2026-11-19　｜　規模：專案　｜　前一份：`2026-11-19-google-gemini-provider-design.md`

## 目的

現在給模型看的只有攤平好的 view `event_details` 和 `resources`，模型不用寫 JOIN，不像真的排程系統。使用者想讓 text2sql 面對接近真實的結構：模型要自己找表、自己寫 JOIN。

這個專案是 AI 工程師作品集，故事是「結構變複雜 → 分數掉多少 → 用什麼方法拉回來」。這份設計只做前半段：建好結構、量出代價。把分數拉回來是下一個專案。

## 目標

- 模型看到的是原始資料表，不再是 view
- 新增組織、會議室、上班時段、請假、假日相關的表，命名乾淨
- 分步量測，每一步只動一件事，量出各自讓分數掉多少
- 舊的 71 題（dev 47、test 24）題目與標準答案完全不變，每一步都重跑對照
- 新表另外有一份 dev 和一份凍結的 test

## 非目標

- 把分數拉回來：改 prompt 規則、動態 few-shot、schema linking、把 view 當成方法加回去，都留給下一個專案
- app 畫面的新表管理功能（新增部門、請假申請…）
- 排程狀態（已取消）、參與者回覆（接受／婉拒）：舊題的標準答案沒有排除已取消或已婉拒的排程，加了會讓舊答案算不算對變得說不清楚
- 重複排程規則、時區、軟刪除
- 老系統式的雜亂命名（縮寫欄位、數字狀態代碼）：之後可以當成另一輪「只加不改」
- 雲端模型的量測：使用者還沒申請 key，之後可以用同一套流程補跑

## 反目標（做了也算失敗）

- 任何一題舊題的標準答案查詢結果改變
- 改寫規則時順手把規則改好或改壞，讓「換成原始表的代價」量不準
- prompt 超過模型的上下文長度被默默截掉，分數掉了其實是因為截斷
- 出新 test 的人看過 dev 的錯誤模式，或之後有人打開 test 的逐題細節

## 限制

- test 集 `evals/heldout_cases.py` 已凍結，不能改
- 標準答案 SQL 查 `events`、`event_details`、`resources`：三張表的結構和 fixture 裡的資料都不能動，`event_details` view 要留在資料庫裡（只是不再給模型看）
- 只加不改的結果：**不能新增資源，也不能新增排程**。舊題有「列出所有會議室」「總共有幾筆排程」「每個人各有幾筆」這類題目，多一筆答案就變。所以新表描述的都是 fixture 現有的 8 個資源：4 個人、2 間會議室、2 個設備
- 本機模型（`qwen2.5:3b`、`qwen3-vl:4b-instruct`）跑在使用者的 GPU，上下文長度受 VRAM 限制
- 自訂的環境變數不要用 `OLLAMA_` 開頭：系統已經設了 `OLLAMA_MODELS`，Ollama 本身也會讀這個開頭的變數

## 做法比較

**對既有評測的處理**

| 做法 | 取捨 | 結果 |
|---|---|---|
| A. 只加不改：舊表與舊資料不動，只加新表 | 舊題可以原封不動重跑，「題目一樣、只有結構變了」的對照很乾淨；代價是不能改既有資料的存法，也不能新增資源與排程 | **使用者選這個** |
| B. 重新設計：照真實系統從頭來，含重複規則、時區、軟刪除 | 更接近真實，但 fixture 與所有標準答案要重寫，舊 test 作廢，之前的分數都不能比 | 不採用 |

**新表的命名**

| 做法 | 取捨 | 結果 |
|---|---|---|
| 1. 命名乾淨，難度來自結構本身（多層 JOIN、自己參照、時間區間、同名欄位、狀態篩選） | 模型還答得對一部分，之後的改進才量得出效果 | **使用者選這個** |
| 2. 再加上老系統的雜亂（縮寫、數字代碼、軟刪除） | 更像很多公司的舊資料庫，但難度一次拉太高，3b 可能幾乎全錯 | 不採用（之後可以另外一輪） |

**view 的角色**

| 做法 | 取捨 | 結果 |
|---|---|---|
| X. 模型看原始的表；view 之後當成「拉回分數」的方法之一來量 | 面對真正的多對多 JOIN；第一步量到的差距同時包含換結構和改寫規則，所以改寫要逐條對應 | **使用者選這個** |
| Y. 模型繼續看 view，新表加在旁邊 | 對照最乾淨，但最核心的 JOIN 還是替模型做好了 | 不採用 |

## 量測步驟

每一步量測都是 `qwen2.5:3b` 與 `qwen3-vl:4b-instruct` 各跑 dev、test，溫度 0，跑一次。test 照現有規則只看總分。

### 步驟 0：固定上下文長度，重建基準

- `text2sql.callOllama` 的 `options` 加上 `num_ctx`，值固定為 8192，寫成程式裡的常數（不放 `.env`：這個值會影響分數，不該因為環境不同而變）。實作時跑一題，用 `ollama ps` 確認模型仍然全部在 GPU 上；放不下再調小，並記在 README
- 現在沒有設 `num_ctx`，Ollama 的預設值依版本而定，不確定是多少，所以要重建基準：用目前的 prompt 重跑舊的 71 題，記成「步驟 0」。如果跟 2026-11-19 README 記的分數不同，照實記錄，之後一律以步驟 0 為基準
- 截斷檢查：每一步量測前，用最長的一題實際呼叫一次 Ollama，看回應的 `prompt_eval_count`（prompt 的 token 數），要小於 `num_ctx` 的一半。數字記在 README。這是手動檢查，不用寫進程式

### 步驟 1：模型改看原始的三張表

- `llm_schema.sql` 改成描述 `events`、`event_resources`、`resources`，附欄位註解，不再出現 `event_details`
- `text2sql.buildMessages` 裡照 view 寫的部分逐條改寫成 JOIN 版本。原則：只換表名、欄位名與 JOIN 寫法，意思不變；不新增也不刪除規則；規則 1、3、4、5、7、10、11 一字不改

| 位置 | 現在 | 改寫方向 |
|---|---|---|
| 規則 2 | 排程相關的問題都查 event_details，不需要 JOIN | 排程在 events，資源在 resources，兩者透過 event_resources 對應；同時用到排程和資源時 JOIN 這三張表 |
| 規則 6 | 列出排程時帶出 resource_name | 列出排程時帶出資源名稱（resources.name） |
| 規則 8 | 指 resource_type = 'person'…；查 resources 表時欄位是 type | 指 resources.type = 'person'…（只剩一種欄位名，後半句刪掉） |
| 規則 9 | event_details 裡一筆排程有幾個資源就有幾列，用 COUNT(DISTINCT event_id) | JOIN event_resources 之後一筆排程有幾個資源就有幾列，用 COUNT(DISTINCT events.id) |
| 規則 12 | event_id IN (SELECT event_id FROM event_details WHERE ...) | events.id IN (SELECT er.event_id FROM event_resources er JOIN resources r ON r.id = er.resource_id WHERE ...) |
| 「目前資料中的值」 | resource_type（resources.type）、resource_name（resources.name） | resources.type、resources.name；category 標成 events.category |
| 3 個 few-shot | FROM event_details | 同樣的問題，SQL 改成 JOIN 版本，查詢結果與原本相同 |

- `tests/test_db.py` 的 `testLlmSchemaHidesTheJoinTable` 改成反過來檢查：schema 說明裡有 `event_resources`、沒有 `event_details`
- 量測結果記成「步驟 1」

### 步驟 2：加新表

新表加在 `schema.sql` 既有內容的後面，`llm_schema.sql` 同步加上說明與欄位註解。

```sql
-- 部門，可以有上層部門
CREATE TABLE departments (
  id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name TEXT NOT NULL,
  parent_id INTEGER REFERENCES departments(id)
);

-- 員工；每個員工對應 resources 裡一個 type = 'person' 的資源
CREATE TABLE employees (
  id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  resource_id INTEGER NOT NULL UNIQUE REFERENCES resources(id),
  department_id INTEGER NOT NULL REFERENCES departments(id),
  job_title TEXT NOT NULL,
  manager_id INTEGER REFERENCES employees(id),
  hired_on DATE NOT NULL
);

-- 會議室的細節；每間對應 resources 裡一個 type = 'room' 的資源
CREATE TABLE rooms (
  resource_id INTEGER PRIMARY KEY REFERENCES resources(id),
  floor SMALLINT NOT NULL,
  capacity SMALLINT NOT NULL,
  has_video_conference BOOLEAN NOT NULL
);

-- 固定班表員工的每週上班時段；輪班的員工沒有這裡的資料，上班時間看 events 裡的 shift
CREATE TABLE work_hours (
  employee_id INTEGER NOT NULL REFERENCES employees(id),
  weekday SMALLINT NOT NULL CHECK (weekday BETWEEN 1 AND 7),  -- 1 = 星期一，與 EXTRACT(ISODOW FROM ...) 相同
  start_time TIME NOT NULL,
  end_time TIME NOT NULL,
  PRIMARY KEY (employee_id, weekday)
);

-- 請假，可以跨好幾天；只有 status = 'approved' 的才算真的請假
CREATE TABLE leave_requests (
  id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  employee_id INTEGER NOT NULL REFERENCES employees(id),
  leave_type TEXT NOT NULL,   -- annual（特休）、sick（病假）、personal（事假）
  start_at TIMESTAMP NOT NULL,
  end_at TIMESTAMP NOT NULL,
  status TEXT NOT NULL,       -- pending（審核中）、approved（核准）、rejected（駁回）
  CHECK (end_at > start_at)
);

-- 不用上班的日子：國定假日與公司特別休假日
CREATE TABLE holidays (
  day DATE PRIMARY KEY,
  name TEXT NOT NULL
);
```

fixture 的新資料（`evals/fixture.py`），具體值留給實作者，但要符合：

- 3 個部門，其中 2 個的上層是第 3 個；4 個人都有員工資料，至少 2 層主管關係，最上層的人 `manager_id` 是 NULL
- 2 間會議室都有細節，樓層、容納人數、視訊設備要有差異，讓「容納 8 人以上」「有視訊的會議室」這類題目篩得出不同結果
- 只有固定班表的員工有 `work_hours`（從 fixture 看，王小明最像固定班表）
- 請假約 5 筆，涵蓋三種狀態與三種假別，至少一筆跨多天、一筆半天。核准的假不能跟那個人的排程重疊；駁回的可以重疊（真實情況常是因為有班才被駁回）
- 假日：一天落在 fixture 期間內、沒有任何排程的平日（例如 2026-11-11 星期三，當作公司特別休假日），加上 fixture 期間之後的幾個國定假日，讓「下一個假日是哪天」答得出來。國定假日的日期要查人事行政總處的公告
- `db.seedDemoData` 也替示範資料的 6 個資源填同樣類型的新資料，app 才問得到
- `seedDemoData` 只在資料庫是空的時候執行，已經有資料的資料庫不會補新表的資料。使用者確認 app 的資料庫裡沒有要保留的資料，所以不寫補資料的程式，README 寫明更新後要先執行 `docker compose down -v` 清空重建（使用者決定）

其他：

- `db.getVocabulary` 加上新表裡實際出現的值：部門名稱、`leave_type`、`status`，跟現有的 category 一樣列在「目前資料中的值」
- prompt 的規則不因新表新增或修改（新表的用法只靠 `llm_schema.sql` 的註解說明）。這樣步驟 2 量到的就只是「表變多」的代價
- 量測：舊的 71 題記成「步驟 2」，新題另外記

### 舊答案不變的檢查

- 在 main 上、開始任何改動之前，產生一份快照 `evals/gold_snapshot.json`：每題（含 `alsoAccept`）的標準答案在 fixture 上的查詢結果，資料列排序後算 hash，只存題號與 hash，不存資料列，所以看不到 test 的答案內容
- 新增一個測試：重建 fixture、重算 hash，跟快照完全一致。步驟 2 加新資料後這個測試必須還是通過

## 新的評測集

- 新題只用在步驟 2 之後；`--split` 多兩個選項給新的 dev 與 test（名稱留給實作者，例如 `dev-ext`、`test-ext`），舊的 `dev`、`test` 不變
- 類別：

| 類別 | 測什麼 | 例子 |
|---|---|---|
| org | 部門、主管：多層 JOIN、自己參照 | 「業務部有哪些人？」「陳大文的主管是誰？」 |
| room | 會議室細節加上排程 | 「明天有排會議的會議室裡，哪間可以視訊？」 |
| hours | 上班時段、假日 | 「王小明星期五幾點下班？」「下一個假日是哪天？」 |
| leave | 請假區間重疊、審核狀態 | 「下週有誰請假？」「誰的假還在審核？」 |
| combo | 排程結合新表 | 「營運部這週總共排了幾個班？」「明天有誰請假但還被排了班？」 |

- 題數：dev 每類 5 題共 25 題；test 每類 3 題共 15 題（一題約 6.7 個百分點，報告時要寫上這個限制）
- 出題原則沿用 `evals/cases.py` 開頭的說明：標準答案只選最少需要的欄位、問時間的題目寫明「開始時間」、避開邊界模糊的問法、`compareAsSet` 與 `alsoAccept` 的用法
- **test 由全新的 subagent 出題**：只給它資料表結構、fixture、類別表與出題原則，不給 dev 題目，也不給任何評測結果。主 session 從頭到尾不打開這個檔案
- 出題到凍結的順序：
  1. fixture 新資料完成
  2. subagent 寫好 test，跑過「標準答案查得到資料」的測試
  3. **停下來等使用者抽查標準答案**。發現錯誤時，由使用者自己改，或另開一個全新的 subagent，把錯在哪裡告訴它去改；主 session 不看題目
  4. 使用者確認後，凍結 commit，同時把 test 的標準答案 hash 加進 `evals/gold_snapshot.json`
  5. 才開始寫 dev
- 凍結之後還是可以為了 dev 增加 fixture 資料，但快照測試必須通過：舊的 71 題和新 test 的答案都不能變。新 test 的答案因此也受到保護，主 session 不用看題目就知道有沒有改到
- dev 由主 session 出，之後調 prompt 時會看
- 現有的檢查套用到新題：題號不重複、test 與 dev 沒有同一題、每個標準答案都查得到資料、不跟 few-shot 重複

## 交付

- 從 `main` 開 `feat/realistic-schema`。快照、步驟 0、1、2 各自分開 commit，量測結果跟該步驟一起 commit，之後回頭對照時才知道哪個分數對應哪份程式
- README 加一張量測表：

| | 3b dev | 3b test | 4b dev | 4b test |
|---|---|---|---|---|
| 步驟 0：固定 num_ctx | | | | |
| 步驟 1：原始三張表 | | | | |
| 步驟 2：加新表（舊題） | | | | |
| 步驟 2：新題（dev-ext／test-ext） | | | | |

- 步驟 1、2 量完，整理 dev 上新出現的錯誤模式（例如漏掉 event_resources、JOIN 後重複計算），寫進 README，當作下一個專案「拉回分數」的起點。這個專案不針對這些錯誤改 prompt
- `.env.example` 不需要改（沒有新設定）

## Claude 決定的細節

- `num_ctx` 固定 8192，寫成常數
- 規則的逐條改寫方向（上表）
- 新表的欄位設計、`work_hours` 只給固定班表的員工、星期幾用 ISO 編號
- 排程狀態與參與者回覆不加
- 新評測集的類別、題數，test 交給全新的 subagent 出題，凍結前停下來等使用者抽查
- 舊答案用 hash 快照檢查
- 錯誤模式只整理、不修

## 留給實作者

- `llm_schema.sql` 註解的確切措辭、few-shot SQL 的確切寫法（查詢結果要跟原本相同）
- fixture 新資料的具體值（在上面的條件內）
- 新 `--split` 的名稱、快照檔的格式
- README 的措辭
