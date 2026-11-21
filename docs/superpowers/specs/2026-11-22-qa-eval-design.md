# 設計：問答準確率評測集

日期：2026-11-22　子專案 5（接在 `2026-11-22-qa-design.md` 之後）

## 目的

為問答（text2sql）建一把固定的尺：同一批題目、同一份資料、同一個「現在」，每次跑出可以互相比較的分數。作品集要講「量測 → 找錯誤模式 → 改進 → 再量測」的故事，這次只做「量測」與「起點分數」，提升分數是下一個子專案。

## 範圍

**做**
- `backend/evals/` 評測套件：固定資料、dev 40 題、test 25 題、結果比對、指令 `python -m evals.run`
- 每題指定提問者，走跟 app 相同的流程（整理資料 → 沙盒 → 模型寫 SQL → 失敗重試一次）
- 評測器本身的 pytest 測試（比對規則、標準答案健檢）
- qwen2.5:3b、qwen3-vl:4b 在 dev、test 的基準分數，寫進根目錄 README

**不做**
- 回答句的評分（另外抽樣人工看）
- 改 prompt、動態 few-shot 等提升分數的工作
- 雲端模型的基準分數（指令支援 `--model`，有 API key 時再跑）

## 已決定的事（2026-11-22）

- 量測範圍：**只量 SQL 的執行結果**
- 提問者：**幾種角色都有**（約 8 題由主管或人資問，其餘一般員工）
- 題數：**dev 40、test 25**
- test 出題：**全新 subagent 出題**，使用者抽查後凍結；主 session 之後只看總分
- 資料來源：**做法 A**，用真的服務函式建固定資料（不手寫沙盒資料、不寫成 pytest 測試）

## 設計

### 檔案

| 檔案 | 責任 |
|---|---|
| `backend/evals/__init__.py` | 空檔 |
| `backend/evals/fixture.py` | 固定的「現在」、固定公司資料（透過服務函式建立）、提問者帳號 |
| `backend/evals/cases.py` | dev 40 題 |
| `backend/evals/heldout_cases.py` | test 25 題（主 session 不打開） |
| `backend/evals/scoring.py` | 結果比對 |
| `backend/evals/gold.py` | 執行標準答案 SQL；失敗只報題號 |
| `backend/evals/gold_snapshot.json` | 每題標準答案結果的 hash |
| `backend/evals/run.py` | 指令 |
| `backend/evals/results/` | 每次執行的 JSON 結果（加入 `.gitignore`） |
| `backend/tests/evals/` | 評測器的 pytest 測試 |

`evals` 不是 app 模組，不登記在 `allModules`，也不進 app 的執行路徑。

### 固定資料

- **現在**：`2026-11-17 14:30`（星期二）。本週 11-16～11-22、上週 11-09～11-15、下週 11-23～11-29。沙盒範圍是前後 90 天。
- **組織**：4 個部門、約 12 位在職員工，兩層主管關係；另有 1 位已離職員工（確認不會出現在 `employees`）。
- **提問者帳號**（代號 → 角色）：
  - `employee`：沒有下屬的一般員工
  - `requester`：自己有多筆請假紀錄的一般員工（問「我」的題目）
  - `manager`：有直屬下屬的主管
  - `hr`：人資（`leave.manage`）
- **班表**：班別有標準班（預設）、早班、晚班、跨午夜的大夜班；幾位員工有週班表；單日調整含「休息日加班」與「上班日改休」；範圍內有 1 個國定假日與 1 個補班日。
- **請假**：待核准、已核准、退回、撤回、取消各至少一筆；跨週末的多天請假；只請幾小時的假；範圍外的舊假（確認不在沙盒）。
- **會議與資源**：會議室 2 間、設備 1 項、公務車 1 輛；多人參加的會議；同時借 2 個資源的會議；1 場已取消的會議。
- 資料以服務函式建立（`orgService`、`shiftService`、`leaveRequests`、`bookingService`），每次執行都相同。請假與會議的建立時間點用固定的 `now`，不受實際日期影響。

### 題目格式

```python
{
  "id": "s03",               # 類別縮寫 + 編號
  "category": "shift",
  "asker": "employee",       # 固定資料的提問者代號
  "question": "黃志強明天上什麼班？",
  "goldSql": "SELECT ...",   # 寫在沙盒的 10 張表上
  "compareAsSet": False,     # 問「有誰」「有哪些」時 True
  "alsoAccept": [],          # 同樣合理的其他寫法（可省略）
}
```

標準答案在**該提問者的沙盒**裡執行，所以權限差異自動反映在答案上（一般員工問別人的假別，標準答案是 `NULL`）。

出題原則（沿用舊版）：
- 標準答案只選回答問題最少需要的欄位；模型多選欄位不扣分
- 要比對時間時，題目明確寫「開始時間」「幾點到幾點」
- 邊界模糊的問法（「9 點以前」）避開資料裡剛好落在邊界的時間
- 問「幾筆」「幾個人」只有一個正確數字，不給替代答案
- 標準答案的結果不得超過 200 列（沙盒上限）

### 類別與題數

| 類別 | dev | test | 例子 |
|---|---|---|---|
| 組織 `org` | 5 | 3 | 工程部有誰、誰是林小美的主管 |
| 班表 `shift` | 8 | 5 | 某人明天上什麼班、下週誰上晚班、跨日班 |
| 誰有空 `avail` | 7 | 4 | 下週二 14–15 點誰有空、某人那天有沒有會議或請假 |
| 請假 `leave` | 8 | 5 | 這週誰請假、某人請什麼假（依提問者不同）、待核准的申請 |
| 會議與資源 `meet` | 7 | 4 | 明天 A 會議室有哪些會議、我下週有幾場會議 |
| 統計 `agg` | 5 | 4 | 每個部門幾個人、這個月誰請假時數最多 |

dev 要涵蓋舊版發現的錯誤模式：「現在」、時長計算、自己加上題目沒問的日期範圍、多資源會議被算成多筆。

### 執行流程（一題）

1. 依 `asker` 取得提問者的 `Actor`，用 `sandbox.collectSandboxData(conn, actor, fixedNow.date())` 整理資料。
2. 用 `sandbox.openSandbox` 開沙盒，以 `sandbox.runQuery` 執行標準答案（含 `alsoAccept`）。失敗或結果被截斷 → 停止整次執行，只報題號（`gold.GoldSqlError`，不帶原例外，避免印出 test 的 SQL）。
3. 呼叫 `service.ask(conn, actor, question, model, qaDatabaseUrl, fixedNow, llm=countingLlm)`。`countingLlm` 包住 `llm.callModel`，記錄呼叫次數（判斷是否用到重試）。
4. 依結果分類（見下）並記錄耗時。

整次執行在 `TEST_DATABASE_URL` 的一個暫時 schema 裡：建立 schema → 跑 migration → 建固定資料 → 逐題 → 刪除 schema。沙盒連線字串由 `TEST_DATABASE_URL` 與 `QA_DB_PASSWORD` 組成（`buildQaDatabaseUrl`）。

### 結果分類

| 標記 | 意義 | 計分 |
|---|---|---|
| ✅ 答對 | 結果與任一標準答案一致 | 對 |
| ❌ 結果不同 | SQL 執行成功但結果不同 | 錯 |
| 💥 SQL 失敗 | 重試後仍失敗（`QA_QUERY_FAILED`，且 `validateSql` 通過） | 錯 |
| 🚫 被擋下 | `QA_QUERY_FAILED` 且最後的 SQL 被 `validateSql` 擋下 | 錯 |
| ⚠️ 模型連不上 | `QA_MODEL_UNAVAILABLE` | **不計分**，另外列出 |

分數 = 答對 ÷（總題數 − 模型連不上）。

### 結果比對（`scoring.resultsMatch`）

沿用舊版規則：
- 數值四捨五入到小數 2 位、字串去頭尾空白後比較；`NULL` 與 `NULL` 相等
- 模型多選欄位不扣分：找得到一組欄位對應讓資料列與標準答案完全相同就算對
- `compareAsSet` 時用集合比較（有沒有 DISTINCT 都對），否則筆數也要相同
- 兩邊都沒有資料算對
- 不比較順序（題目問「最多」「排名」時，標準答案用 `LIMIT` 限定，而不是靠順序）

### 指令與輸出

```
python -m evals.run --split dev|test [--model 模型名稱] [--filter 類別或題號]
```

- `--model` 預設 `.env` 的 `OLLAMA_MODEL`，必須在 `llm.listModels()` 裡
- `--filter` 只能用在 dev
- **dev**：每題印標記、題號、模型 SQL；結果不同時印兩邊前 5 列；最後印各類別分數表與重試次數；完整結果存 `results/dev-<模型>-<時間>.json`
- **test**：只印進度（第幾題／共幾題）與總分；JSON 只存總分、模型、時間與「模型連不上」的題數

### 保護 test 題

- 出題 subagent 只拿到：固定資料（`fixture.py`）、10 張沙盒表的說明、題目格式、類別配額與出題原則。不給 dev 題、不給 prompt。
- 使用者抽查幾題後 commit 凍結。主 session 之後**不打開** `heldout_cases.py`、不看 test 的每題結果。
- 標準答案執行失敗只報題號。
- `gold_snapshot.json`：每題標準答案結果（正規化後）的 SHA-256。執行時比對，不符就停止並報題號——改了固定資料或沙盒邏輯導致答案改變時，必須人工確認後才能更新快照（`python -m evals.run --update-snapshot`，只在使用者同意後執行）。

### 測試（pytest，`backend/tests/evals/`）

- `scoring`：多選欄位、集合比較、筆數不同、`NULL`、浮點數與 Decimal、兩邊都空
- 固定資料健檢：提問者帳號存在、已離職員工與範圍外的請假不在沙盒、取消的會議不在沙盒
- 標準答案健檢：dev 與 test 每題的標準答案在對應沙盒都執行成功、沒有被截斷、hash 與快照相符；失敗只報題號
- 這些測試不呼叫模型

## 怎麼驗證

1. `python -m pytest tests/evals -q`：全部通過
2. `python -m evals.run --split dev`：40 題都有標記，最後有分類分數表，`results/` 多一個 JSON
3. `python -m evals.run --split test`：只看到進度與總分
4. 故意改壞 dev 一題的標準答案：執行器停止並只報那個題號
5. 根目錄 README 的「問答準確率」一節有 3b、4b 的 dev 與 test 分數（4b 若因記憶體不足中止，由使用者在自己的終端機補跑）

## 留給建造者決定

- 固定資料裡的人名、部門名、會議標題
- dev 每題的實際問法與標準答案寫法
- 輸出的排版細節
