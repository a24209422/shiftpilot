# 排程工具 MVP（text2sql）

用中文問排程問題，本機 Ollama 模型把問題轉成 SQLite 查詢並回傳結果。新增排程時會自動檢查同一資源的時段衝突。

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

- **固定資料**：`evals/fixture.py` 有 8 個資源、40 筆排程，「現在」固定在 2026-11-17（二）14:30，所以每次跑的題目和答案都一樣
- **題目**：`evals/cases.py` 共 41 題，分 6 類。每題附一句標準答案 SQL
- **比對**：比的是查詢結果，不是 SQL 文字。模型多選欄位不扣分，但標準答案的欄位和資料列必須都在
- **流程**：走跟 app 相同的 `answerQuestion`，包含 SQL 出錯時重試一次

### 基準分數（2026-11-17，各跑一次，溫度 0）

| 類別 | 測什麼 | 題數 | qwen2.5:3b | qwen3-vl:4b-instruct |
|---|---|---|---|---|
| basic | 基本篩選 | 6 | 3 | 5 |
| date | 今天、明天、星期幾、上下週 | 10 | 6 | 10 |
| aggregate | COUNT、SUM、GROUP BY | 9 | 6 | 7 |
| type | 人、會議室、設備對應到 `type` | 6 | 4 | 6 |
| time | 一天中的時段、時長 | 5 | 1 | 3 |
| order | 排序與 LIMIT | 5 | 2 | 5 |
| **合計** | | **41** | **22（53.7%）** | **36（87.8%）** |
| 平均每題秒數 | | | 3.6 | 13.7 |

秒數是在開發機上量的，不含第一題載入模型的時間。

## 結構

| 檔案 | 內容 |
|---|---|
| `schema.sql` | 資料表定義，同時當作 text2sql 的 schema 說明 |
| `db.py` | 資料庫操作、衝突檢查、唯讀查詢、示範資料 |
| `text2sql.py` | 組 prompt（schema、資料中的實際值、日期對照表、few-shot）、呼叫 Ollama、SQL 檢查、失敗重試 |
| `app.py` | Streamlit 介面：自然語言查詢、排程清單、新增排程、資源 |
| `evals/` | text2sql 評測集：固定資料、題目與標準答案、比對邏輯、跑分腳本 |
| `tests/` | 自動化測試 |

## text2sql 的唯讀防護

1. `validateSql`：只接受單一 `SELECT` / `WITH`，擋寫入關鍵字
2. 以 `mode=ro` 唯讀模式開啟 SQLite
3. `PRAGMA query_only = ON`

## 目前限制（之後擴充的方向）

- 一筆排程只能對應一個資源；多人會議目前要建多筆。通用化時可改成 `event_resources` 多對多表
- 不支援跨日排程（例如 22:00–隔天 06:00 的大夜班）、重複排程
- 「誰有空」這類找空檔的問題，小模型只會列出該時段的排程，要使用者自己判斷
