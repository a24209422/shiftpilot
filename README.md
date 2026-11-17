# 排程工具 MVP（text2sql）

用中文問排程問題，本機 Ollama 模型把問題轉成 SQLite 查詢並回傳結果。一筆排程可以有多個資源（例如幾個人加一間會議室），新增時會自動檢查每個資源的時段衝突。

## 執行

```bash
pip install -r requirements.txt
streamlit run app.py
```

- 需要 Ollama 在背景執行，並已下載 `.env` 指定的模型（預設 `qwen2.5:3b`）
- 想換模型：複製 `.env.example` 成 `.env`，修改 `OLLAMA_MODEL`
- 第一次啟動會建立 `schedule.db`，並以「今天」為基準塞入兩週的示範資料

## 測試

```bash
python -m pytest -q
```

測試用假的 LLM，不需要 Ollama。

## text2sql 評測

改 prompt、換模型或改資料表之後，用評測集確認準確率是變好還是變差。需要 Ollama。

```bash
python -m evals.run
```

- `--model qwen3-vl:4b-instruct`：指定模型（預設讀 `.env` 的 `OLLAMA_MODEL`）
- `--filter date` 或 `--filter d05`：只跑某個類別或某一題
- 每題的結果與模型寫的 SQL 會存到 `evals/results/`（不進 git）

做法：

- **固定資料**：`evals/fixture.py` 有 8 個資源、35 筆排程（其中 5 場會議有 2 個資源），「現在」固定在 2026-11-17（二）14:30，所以每次跑的題目和答案都一樣
- **題目**：`evals/cases.py` 共 47 題，分 7 類。每題附一句標準答案 SQL
- **比對**：比的是查詢結果，不是 SQL 文字。模型多選欄位不扣分，但標準答案的欄位和資料列必須都在
- **替代答案**：列出排程的題目，一場 2 個資源的會議列一次或列兩次都算對；問「幾筆」「幾場」的題目只有一個正確數字
- **流程**：走跟 app 相同的 `answerQuestion`，包含 SQL 出錯時重試一次

### 基準分數（2026-11-17，各跑一次，溫度 0）

| 類別 | 測什麼 | 題數 | qwen2.5:3b | qwen3-vl:4b-instruct |
|---|---|---|---|---|
| basic | 基本篩選 | 6 | 3 | 5 |
| date | 今天、明天、星期幾、上下週 | 10 | 5 | 9 |
| aggregate | COUNT、SUM、GROUP BY | 9 | 5 | 7 |
| type | 人、會議室、設備對應到資源種類 | 6 | 5 | 6 |
| time | 一天中的時段、時長 | 5 | 2 | 3 |
| order | 排序與 LIMIT | 5 | 4 | 4 |
| multi | 一筆排程有多個資源 | 6 | 1 | 3 |
| **合計** | | **47** | **25（53.2%）** | **37（78.7%）** |
| 平均每題秒數 | | | 3.5 | 13.0 |

秒數是在開發機上量的，不含第一題載入模型的時間。

### 和改成多對多之前比較

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
- 舊版（一筆排程只有一個資源）建立的 `schedule.db` 結構不相容，沒有提供資料遷移

## text2sql 的唯讀防護

1. `validateSql`：只接受單一 `SELECT` / `WITH`，擋寫入關鍵字
2. 以 `mode=ro` 唯讀模式開啟 SQLite
3. `PRAGMA query_only = ON`

## 目前限制（之後擴充的方向）

- 不支援跨日排程（表單只能選同一天，例如排不了 22:00–隔天 06:00 的大夜班）、重複排程
- 「誰有空」這類找空檔的問題，小模型只會列出該時段的排程，要使用者自己判斷
