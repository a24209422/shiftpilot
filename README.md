# 排程工具 MVP（text2sql）

用中文問排程問題，本機 Ollama 模型把問題轉成 PostgreSQL 查詢並回傳結果。一筆排程可以有多個資源（例如幾個人加一間會議室），新增時會自動檢查每個資源的時段衝突。

## 執行

需要 Docker，以及在主機上執行的 Ollama，並已下載 `.env` 指定的模型（預設 `qwen2.5:3b`）。

```bash
cp .env.example .env                  # 再把 .env 裡的兩組 change-me 密碼改成自己的值（只用英文和數字）
docker compose up -d --build --wait   # 建置並啟動 app 與 PostgreSQL 17
```

打開 http://127.0.0.1:8501 。

- app 和 PostgreSQL 都在容器裡；Ollama 留在主機上，app 透過 `host.docker.internal` 連線，可以直接用主機的 GPU，模型也不用重新下載
- 網頁只綁在本機的 `127.0.0.1:8501`：還沒有登入功能，所以不開放給內網
- 改了程式之後，執行 `docker compose up -d --build` 重建 app
- 換模型：「自然語言查詢」分頁的下拉選單可以切換模型，預設選 `.env` 的 `OLLAMA_MODEL`，選單裡的本機模型列在 `LOCAL_MODELS`。改了 `.env` 之後執行 `docker compose up -d`
- 用雲端模型：在 `.env` 填 `OPENROUTER_API_KEY`（到 openrouter.ai 申請），執行 `docker compose up -d` 後，選單會出現 `OPENROUTER_MODELS` 列出的模型。用雲端模型時，問題、資料表結構和資源名稱會送到 OpenRouter，再轉給模型的廠商
- 用 Google 的 Gemini（直連，不經過 OpenRouter）：Google AI Pro 每月附 Cloud credits，OpenRouter 用不到，所以要直連。步驟：到 Google AI Studio 領取 credits、綁定帳單（第三方資料說可能要先預付 US$5，以 AI Studio 畫面為準）、建立 API key，填進 `.env` 的 `GOOGLE_AI_API_KEY`，執行 `docker compose up -d` 後，選單會出現 `GOOGLE_AI_MODELS` 列出的模型。資料會送到 Google。各家獨立：只填 Google 的 key，選單就只多出 Google 的模型；同一個模型名稱同時列在兩家時，以 OpenRouter 為準
- 兩個容器都設定成自動重啟，電腦重開機、Docker 啟動後會自己跑起來
- PostgreSQL 另外綁在本機的 `127.0.0.1:5433`，給本機跑測試和評測用，避開常被其他 PostgreSQL 占用的 5432
- 容器第一次啟動時，`docker/init/` 會建立非 superuser 的 `schedule_app` 帳號，以及 `schedule`（app 用）、`schedule_test`（測試與評測用）兩個資料庫
- app 第一次啟動會建表，並以「今天」為基準塞入兩週的示範資料
- 想清空資料重來：`docker compose down -v`（會刪掉整個資料庫，包含帳號）
- 從加入部門、員工、請假這幾張表之前的版本更新時，要先清空重建（`docker compose down -v` 再 `docker compose up -d --build --wait`）：示範資料只在資料庫是空的時候寫入，沒清空的話新表會建出來但是空的，在畫面上問新表的問題查不到東西

### 本機開發

改程式時想馬上看到結果，可以只在容器裡跑 PostgreSQL，app 直接在本機執行：

```bash
docker compose stop app               # app 容器也占用 8501，先停掉
docker compose up -d --wait postgres
pip install -r requirements.txt
streamlit run app.py
```

## 測試

```bash
python -m pytest -q
```

需要先啟動 PostgreSQL。每個測試在 `schedule_test` 裡建立自己的 schema，跑完就刪掉。測試用假的 LLM，不需要 Ollama。

## text2sql 評測

改 prompt、換模型或改資料表之後，用評測集確認準確率是變好還是變差。需要 Ollama 和 PostgreSQL。

```bash
python -m evals.run               # dev：調 prompt 時用，印出每題的對錯與模型寫的 SQL
python -m evals.run --split test  # test：確認改進有沒有效，只印分數
```

- `--model qwen3-vl:4b-instruct`：指定模型，可以是本機 Ollama 模型，或 `OPENROUTER_MODELS`、`GOOGLE_AI_MODELS` 裡的雲端模型（需要對應的 `OPENROUTER_API_KEY` 或 `GOOGLE_AI_API_KEY`，例如 `--model anthropic/claude-haiku-5.5`、`--model gemini-3.5-flash-lite`）。預設讀 `.env` 的 `OLLAMA_MODEL`
- `--filter date` 或 `--filter d05`：只跑某個類別或某一題（只限 dev）
- 每題的結果與模型寫的 SQL 會存到 `evals/results/`（不進 git）。test 的報告檔不要打開看每題的細節

做法：

- **固定資料**：`evals/fixture.py` 有 8 個資源、35 筆排程（其中 5 場會議有 2 個資源），「現在」固定在 2026-11-17（二）14:30，所以每次跑的題目和答案都一樣
- **題目**：分成兩份，每題附一句標準答案 SQL
  - dev：`evals/cases.py` 47 題，分 7 類。調 prompt 時看每題的對錯，找出模型的錯誤模式
  - test：`evals/heldout_cases.py` 24 題，各類別題數照 dev 的比例縮小。2026-11-18 在改 prompt 之前寫好並凍結，之後不再修改，只用來確認改進不是只對 dev 有效
  - test 和調 prompt 的是同一個人出的題，出題時已經知道 dev 上的錯誤模式，獨立性不如由別人出題
- **比對**：比的是查詢結果，不是 SQL 文字。模型多選欄位不扣分，但標準答案的欄位和資料列必須都在
- **替代答案**：列出排程的題目，一場 2 個資源的會議列一次或列兩次都算對；問「幾筆」「幾場」的題目只有一個正確數字
- **流程**：走跟 app 相同的 `answerQuestion`，包含 SQL 出錯時重試一次
- **連線錯誤**：雲端模型遇到 HTTP 429 或 5xx 時，會等 2 秒、4 秒再試，最多 3 次。還是失敗的題目印成 `ERROR`，記成連線錯誤，不算答錯，也不計入題數；分數下方會列出「另有 N 題連線錯誤沒有計分」，看到這行要重跑，這輪的分數不能跟其他輪比較

### 基準分數：加規則之前（2026-11-18，PostgreSQL，溫度 0）

| | qwen2.5:3b | qwen3-vl:4b-instruct |
|---|---|---|
| dev（47 題） | 25（53.2%） | 41（87.2%） |
| test（24 題） | 15（62.5%） | 15（62.5%） |

- 4b 在 test 比 dev 低將近 25 個百分點。dev 的題目在之前調 prompt 時都看過，dev 分數可能因此偏高；原因沒有逐題確認，因為看了 test 的細節，test 就不算沒看過的題目了
- test 只有 24 題，一題就是 4.2 個百分點

dev 各類別：

| 類別 | 測什麼 | 題數 | qwen2.5:3b | qwen3-vl:4b-instruct |
|---|---|---|---|---|
| basic | 基本篩選 | 6 | 3 | 6 |
| date | 今天、明天、星期幾、上下週 | 10 | 7 | 10 |
| aggregate | COUNT、SUM、GROUP BY | 9 | 6 | 8 |
| type | 人、會議室、設備對應到資源種類 | 6 | 4 | 6 |
| time | 一天中的時段、時長 | 5 | 2 | 4 |
| order | 排序與 LIMIT | 5 | 1 | 4 |
| multi | 一筆排程有多個資源 | 6 | 2 | 3 |
| **合計** | | **47** | **25（53.2%）** | **41（87.2%）** |
| 平均每題秒數 | | | 3.6 | 9.8 |

秒數是在開發機上量的，不含第一題載入模型的時間。

- dev 各跑 3 次，每一題的對錯都相同：溫度 0、同一台機器上，改 prompt 後跑一次就夠，分數的變化來自改動本身，不是隨機。test 各跑 1 次，平均每題秒數是 3.8 和 13.7
- 改成 PostgreSQL 之前（SQLite 語法）兩個模型分別是 25 和 37 題。資料庫和 prompt 裡的語法說明是一起改的，分不出差異來自哪一項

### 加入靜態規則之後（2026-11-19）

看過 dev 的錯題之後，在 prompt 加了三條規則和一個 few-shot 範例：

- 規則 10：這是 PostgreSQL，不要用 `julianday()`、`strftime()` 這類 SQLite 函式；時長用 `EXTRACT(EPOCH FROM end_at - start_at) / 3600` 換算成小時
- 規則 11：問「下一個」「接下來」時用 `start_at >` 現在時間；問某個時間點「正在進行」時用 `start_at <= 該時間點 AND end_at > 該時間點`
- 規則 12：找兩個資源一起參與的排程（例如某人在某間會議室開的會）時，用 `event_id IN (子查詢)`
- 新增一個不帶日期條件的 few-shot：原本兩個範例都有日期條件，小模型會照抄，連沒問日期的題目也加上日期範圍
- 規則 7 補上「不要猜排程名稱屬於哪個 category」，規則 8 把「誰」也對應到人

| | qwen2.5:3b | qwen3-vl:4b-instruct |
|---|---|---|
| dev（47 題） | 25 → 31（53.2% → 66.0%） | 41 → 43（87.2% → 91.5%） |
| test（24 題） | 15 → 13（62.5% → 54.2%） | 15 → 16（62.5% → 66.7%） |

dev 各類別（加規則之前 → 之後）：

| 類別 | 題數 | qwen2.5:3b | qwen3-vl:4b-instruct |
|---|---|---|---|
| basic | 6 | 3 → 5 | 6 → 6 |
| date | 10 | 7 → 7 | 10 → 9 |
| aggregate | 9 | 6 → 5 | 8 → 9 |
| type | 6 | 4 → 5 | 6 → 6 |
| time | 5 | 2 → 4 | 4 → 4 |
| order | 5 | 1 → 3 | 4 → 4 |
| multi | 6 | 2 → 2 | 3 → 5 |
| **合計** | **47** | **25 → 31** | **41 → 43** |
| 平均每題秒數 | | 3.6 → 3.4 | 9.8 → 12.1 |

- dev 兩個模型都進步，但這些規則是看 dev 的錯題寫的，進步有一部分可能只對 dev 有效
- 改 prompt 時，原本對的題目也可能變錯：4b 在 dev 修好 5 題（a07、m04、o01、x01、x03），但原本對的 d04、m01、o03 變錯
- test 一題是 4.2 個百分點，3b 少 2 題、4b 多 1 題。改 prompt 本來就會讓幾題對錯互換，±2 題以內不足以判斷 test 有沒有改善
- 各跑 1 次，溫度 0

### 結構變複雜的代價（2026-11-19 起）

之前給模型看的是攤平好的 view `event_details`，模型不用寫 JOIN，不像真的排程系統。這一節量的是：模型改看原始的資料表、再加上組織與可用時間的新表之後，同一批題目的分數掉多少。設計見 [`docs/superpowers/specs/2026-11-19-realistic-schema-design.md`](docs/superpowers/specs/2026-11-19-realistic-schema-design.md)。分三步，每一步只動一件事：

- 步驟 0：固定 Ollama 的上下文長度，用現在的 prompt 重跑舊的 71 題，當作之後所有比較的基準
- 步驟 1：模型改看原始的 `events`、`event_resources`、`resources`，照 view 寫的規則和範例逐條改寫成 JOIN 版本
- 步驟 2：加 6 張新表（部門、員工、會議室細節、上班時段、請假、假日），舊題再跑一次，另外跑新表的新題

| | 3b dev | 3b test | 4b dev | 4b test |
|---|---|---|---|---|
| 步驟 0：固定 `num_ctx` | 31/47（66.0%） | 13/24（54.2%） | 43/47（91.5%） | 16/24（66.7%） |
| 步驟 1：原始三張表 | 31/47（66.0%） | 13/24（54.2%） | 44/47（93.6%） | 16/24（66.7%） |
| 步驟 2：加新表（舊題） | | | | |
| 步驟 2：新題（dev-ext／test-ext） | | | | |

溫度 0，各跑 1 次。test 一題是 4.2 個百分點；之後新題的 test-ext 只有 15 題，一題約 6.7 個百分點。

**步驟 0：固定 `num_ctx`**

- `callOllama` 加上 `num_ctx: 8192`（`text2sql.ollamaNumCtx`）。沒設的時候預設值依 Ollama 版本而定，prompt 超過上限會被默默截掉、不報錯，分數掉了就分不出是模型問題還是被截斷。這個值會影響分數，所以寫死在程式裡，不放 `.env`
- 截斷檢查：用最長的 dev 題目，兩個模型的 prompt 都是 1596 個 token，遠小於 8192（檢查的做法是先 `ollama stop` 避免快取讓數字偏低，再看回應的 `prompt_eval_count`）。步驟 1、2 會再量
- 分數跟 2026-11-19「加入靜態規則之後」完全一樣：兩個模型的 dev、test 總分和 dev 每個類別的對錯數都相同，所以固定 `num_ctx` 沒有改變結果，之後以這一列為基準
- 這張卡是 GTX 1650（4 GB）：3b 在 8192 時 100% 在 GPU；4b 放不下，`ollama ps` 顯示 8192 時約 40% 在 GPU，降到 4096 是 45%、2048 是 50%，調小也不會讓它全進 GPU。先前的基準沒有記 GPU 占比，不確定當時 4b 是不是也有一部分跑在 CPU。平均每題秒數（dev，不含第一題）：3b 3.4、4b 12.7

**步驟 1：模型改看原始的三張表**

- `llm_schema.sql` 改成描述 `events`、`event_resources`、`resources`，不再出現 `event_details`。prompt 裡規則 2、6、8、9、12、「目前資料中的值」和 3 個 few-shot 範例逐條改寫成 JOIN 版本，其餘規則一字不改；範例改寫後的查詢結果跟原本相同（`testFewShotResultsMatchViewVersion` 檢查）
- 截斷檢查：prompt 是 1716 個 token（步驟 0 是 1596），遠小於 8192
- **總分沒有掉**：3b 的 dev、test 跟步驟 0 完全相同（31、13）；4b dev 多對 1 題（43 → 44），test 不變（16）。這跟原本的預期相反，本來以為改成要自己寫 JOIN 之後分數會明顯下降
- 總分相同不代表答案相同：3b 在 dev 有 10 題對錯互換（5 題變對、5 題變錯），各類別也有增有減（date 7 → 6、time 4 → 3、multi 2 → 1，aggregate、type、order 各 +1）。4b 只有 m01 變對，其餘對錯不變（錯的是 d04、o03、x05）。能確定的只有總分沒有掉；3b 的 10 題互換比先前幾次改動（4 到 8 題）還多，不能說結構完全沒有影響
- 新出現的錯誤模式（只看 dev 的 SQL，沒有針對它們改 prompt）：
  - 題目沒問到卻加上 `resources.type = 'person'` 篩選：3b 的 SQL 裡出現這個條件的題數從 5 題增加到 11 題（4b 從 4 題到 7 題）。3b 有 3 題因此答錯：b05（公務車是設備，篩選後查不到）、d02（明天有哪些行程，只剩有人參加的排程）、x05（教育訓練的資源數，會議室被篩掉）。步驟 0 的 view 版本沒有這種情況；可能跟規則 8 改寫成 `resources.type = 'person'` 有關，沒有驗證
  - 用 `GROUP BY events.title` 代替 `events.id` 分組：3b 的 x04（哪些排程有兩個以上的資源），標題相同的不同排程會被合併。步驟 0 用 `event_id` 子查詢答對
- 其餘互換的題目（3b 的 m05、o01 變錯，以及變對的 5 題）是日期或時間條件的寫法變了，看不出跟 JOIN 有關。答錯的題目裡，沒有因為 JOIN 之後重複計算而錯的
- 平均每題秒數（dev，不含第一題）：3b 3.8（步驟 0 是 3.4）、4b 18.7（步驟 0 是 12.7）。4b 這一輪是在系統記憶體不足、背景工作被中止後重跑的，秒數不能當成結構的影響

dev 各類別：

| 類別 | 題數 | 3b 步驟 0 | 3b 步驟 1 | 4b 步驟 0 | 4b 步驟 1 |
|---|---|---|---|---|---|
| basic | 6 | 5 | 5 | 6 | 6 |
| date | 10 | 7 | 6 | 9 | 9 |
| aggregate | 9 | 5 | 6 | 9 | 9 |
| type | 6 | 5 | 6 | 6 | 6 |
| time | 5 | 4 | 3 | 4 | 5 |
| order | 5 | 3 | 4 | 4 | 4 |
| multi | 6 | 2 | 1 | 5 | 5 |
| **合計** | **47** | **31** | **31** | **43** | **44** |

### 和改成多對多之前比較（SQLite 時期）

改結構之前（一筆排程只有一個資源，模型要自己寫 JOIN）跑過同一批題目中的 41 題：

| 同樣的 41 題 | qwen2.5:3b | qwen3-vl:4b-instruct |
|---|---|---|
| 改之前 | 22 | 36 |
| 改之後 | 24 | 34 |
| 對錯互換的題數 | 8（多對 5、少對 3） | 4（多對 1、少對 3） |

每種情況只跑一次，而且同一個模型就有 4 到 8 題對錯互換，所以 ±2 題的差距不足以判斷新結構比較好或比較差。能確定的是新增的 multi 類題目兩個模型都不擅長。

## 結構

| 檔案 | 內容 |
|---|---|
| `Dockerfile` | app 的映像檔，只包含執行需要的檔案，以非 root 帳號執行 |
| `docker-compose.yml` | app 與 PostgreSQL 17 兩個容器，密碼從 `.env` 讀取 |
| `docker/init/` | 容器第一次啟動時建立 app 帳號與資料庫 |
| `schema.sql` | 資料表與 view 的定義 |
| `llm_schema.sql` | 寫給 text2sql 模型看的結構說明：原始資料表與欄位註解，不含 view |
| `db.py` | 資料庫操作、衝突檢查、唯讀查詢、示範資料 |
| `text2sql.py` | 組 prompt（schema、資料中的實際值、日期對照表、few-shot）、呼叫 Ollama、OpenRouter 或 Google、SQL 檢查、失敗重試 |
| `app.py` | Streamlit 介面：自然語言查詢、排程清單、新增排程、資源 |
| `evals/` | text2sql 評測集：固定資料、題目與標準答案、比對邏輯、跑分腳本 |
| `tests/` | 自動化測試 |

## 資料結構

| 名稱 | 內容 |
|---|---|
| `resources` | 可被排程的對象，用 `type` 區分人、會議室、設備 |
| `events` | 排程，一筆排程一列 |
| `event_resources` | 排程和資源的多對多關聯：一場會議可以同時有多個人和一間會議室 |
| `event_details`（view） | 攤平成「一筆排程 × 一個資源」一列；模型看不到它，評測集舊的標準答案在用 |
| `departments` | 部門，`parent_id` 指向上層部門 |
| `employees` | 員工：對應一個 `type = 'person'` 的資源，有部門、職稱、主管（`manager_id` 指向另一個員工）、到職日 |
| `rooms` | 會議室的細節：對應一個 `type = 'room'` 的資源，有樓層、容納人數、有沒有視訊設備 |
| `work_hours` | 固定班表員工的每週上班時段（`weekday` 1 = 星期一）；輪班的員工沒有資料，上班時間看 `events` 裡的班別 |
| `leave_requests` | 請假，可以跨好幾天；`status` 是 `pending`、`approved`、`rejected`，只有核准的才算請假 |
| `holidays` | 國定假日與公司特別休假日 |

- text2sql 的模型看的是原始的 `events`、`event_resources`、`resources`，要自己寫 JOIN；一筆排程有幾個資源，JOIN 之後就有幾列，算筆數時要用 `COUNT(DISTINCT events.id)`。改成這樣對分數的影響見「結構變複雜的代價」
- 新增排程時，只要有任何一個資源在該時段已有排程，整筆都不會新增
- `event_resources.position` 記錄新增排程時選資源的順序，清單上的資源才會照使用者選的順序顯示
- 改成 PostgreSQL 之前的 `schedule.db`（SQLite）不會搬過來；裡面只有示範資料，新資料庫啟動時會重新塞入

## text2sql 的唯讀防護

1. `validateSql`：只接受單一 `SELECT` / `WITH`，擋寫入關鍵字
2. 模型寫的 SQL 在 read-only transaction 裡執行，PostgreSQL 本身會拒絕寫入
3. app 用非 superuser 的 `schedule_app` 帳號連線：superuser 可以用 `pg_read_file()` 這類函式讀取伺服器上的檔案

## 目前限制（之後擴充的方向）

- 不支援跨日排程（表單只能選同一天，例如排不了 22:00–隔天 06:00 的大夜班）、重複排程
- 「誰有空」這類找空檔的問題，小模型只會列出該時段的排程，要使用者自己判斷
