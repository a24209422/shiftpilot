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

## 結構

| 檔案 | 內容 |
|---|---|
| `schema.sql` | 資料表定義，同時當作 text2sql 的 schema 說明 |
| `db.py` | 資料庫操作、衝突檢查、唯讀查詢、示範資料 |
| `text2sql.py` | 組 prompt（schema、資料中的實際值、日期對照表、few-shot）、呼叫 Ollama、SQL 檢查、失敗重試 |
| `app.py` | Streamlit 介面：自然語言查詢、排程清單、新增排程、資源 |

## text2sql 的唯讀防護

1. `validateSql`：只接受單一 `SELECT` / `WITH`，擋寫入關鍵字
2. 以 `mode=ro` 唯讀模式開啟 SQLite
3. `PRAGMA query_only = ON`

## 目前限制（之後擴充的方向）

- 一筆排程只能對應一個資源；多人會議目前要建多筆。通用化時可改成 `event_resources` 多對多表
- 不支援跨日排程（例如 22:00–隔天 06:00 的大夜班）、重複排程
- 「誰有空」這類找空檔的問題，小模型只會列出該時段的排程，要使用者自己判斷
