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
- 想換模型：修改 `.env` 的 `OLLAMA_MODEL`，再執行 `docker compose up -d`
- 兩個容器都設定成自動重啟，電腦重開機、Docker 啟動後會自己跑起來
- PostgreSQL 另外綁在本機的 `127.0.0.1:5433`，給本機跑測試和評測用，避開常被其他 PostgreSQL 占用的 5432
- 容器第一次啟動時，`docker/init/` 會建立非 superuser 的 `schedule_app` 帳號，以及 `schedule`（app 用）、`schedule_test`（測試與評測用）兩個資料庫
- app 第一次啟動會建表，並以「今天」為基準塞入兩週的示範資料
- 想清空資料重來：`docker compose down -v`（會刪掉整個資料庫，包含帳號）

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

- `--model qwen3-vl:4b-instruct`：指定模型（預設讀 `.env` 的 `OLLAMA_MODEL`）
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
| `llm_schema.sql` | 寫給 text2sql 模型看的結構說明，只有 `event_details` 和 `resources` |
| `db.py` | 資料庫操作、衝突檢查、唯讀查詢、示範資料 |
| `text2sql.py` | 組 prompt（schema、資料中的實際值、日期對照表、few-shot）、呼叫 Ollama、SQL 檢查、失敗重試 |
| `app.py` | Streamlit 介面：自然語言查詢、排程清單、新增排程、資源 |
| `evals/` | text2sql 評測集：固定資料、題目與標準答案、比對邏輯、跑分腳本 |
| `tests/` | 自動化測試 |

## 資料結構

| 名稱 | 內容 |
|---|---|
| `resources` | 可被排程的對象，用 `type` 區分人、會議室、設備 |
| `events` | 排程，一筆排程一列 |
| `event_resources` | 排程和資源的多對多關聯：一場會議可以同時有多個人和一間會議室 |
| `event_details`（view） | 攤平成「一筆排程 × 一個資源」一列 |

- text2sql 的模型只看得到 `event_details` 和 `resources`，不用自己寫 JOIN。代價是一筆排程在 view 裡有多列，算筆數時要用 `COUNT(DISTINCT event_id)`
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
