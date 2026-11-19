# 讓 text2sql 面對接近真實的資料庫結構 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 模型改看原始資料表、再加上 6 張組織與可用時間的新表，分三步量出結構變複雜讓 text2sql 分數掉多少，舊的 71 題答案全程不變。

**Architecture:** 先用 hash 快照鎖住舊題標準答案的查詢結果（`evals/snapshot.py`）。步驟 0 在 `callOllama` 固定 `num_ctx`；步驟 1 改寫 `llm_schema.sql` 與 `text2sql.buildMessages` 裡照 view 寫的規則和 few-shot；步驟 2 在 `schema.sql` 加新表，`db.addOrganizationData` 同時給 fixture 與示範資料用。新評測集分 `dev-ext`（主 session 出題）與 `test-ext`（全新 subagent 出題、使用者抽查後凍結）。

**Tech Stack:** Python 3.13、PostgreSQL 17、psycopg 3、pytest、Ollama

**Spec:** `docs/superpowers/specs/2026-11-19-realistic-schema-design.md`

## Global Constraints

- 縮排 2 個空白；camelCase；註解用正體中文，只寫「為什麼」
- 不新增套件，不新增環境變數
- **絕對不要打開或讀取** `evals/heldout_cases.py`、`evals/ext_heldout_cases.py`（Task 5 建立後）、`evals/results/` 裡檔名有 `-test-` 或 `-test-ext-` 的報告；也不要對這兩個題目檔執行 `git diff`、`git show`、`cat`、`grep`。test 只看 `evals.run` 印出的總分
- `resources`、`events`、`event_resources` 的結構、`event_details` view、fixture 裡既有的資源與排程都不改；fixture **不新增資源、不新增排程**
- `num_ctx` 固定 8192，寫成 `text2sql.ollamaNumCtx` 常數
- prompt 規則 1、3、4、5、7、10、11 一字不改；步驟 2 不新增或修改任何規則；整個專案不為了提高分數改 prompt
- 量測：`qwen2.5:3b` 與 `qwen3-vl:4b-instruct`，溫度 0，各跑一次。出現「另有 N 題連線錯誤沒有計分」就重跑那一輪
- 分支 `feat/realistic-schema`；commit 訊息用正體中文，結尾加 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`；不 push

## Review Focus

1. 已經有資料的資料庫再跑一次 `initDb`（app 每次啟動都會跑）→ 新表建出來、舊資料不受影響、不報錯（Task 4：`testInitDbTwiceKeepsDemoData`）
2. `addOrganizationData` 裡寫了不存在的資源名稱 → 丟 `ValueError`，新表一筆都沒寫入（Task 4：`testAddOrganizationDataRejectsUnknownResourceAndSavesNothing`）
3. 標準答案 SQL 沒有 ORDER BY，兩次查詢的資料列順序不同 → hash 仍然相同，快照測試不會隨機失敗（Task 1：`testHashRowsIgnoresRowOrder`）
4. 重新產生快照時，某題的答案其實已經變了 → 拒絕覆寫並列出題號，不會把錯的答案寫成新快照（Task 1：`testMergeSnapshotRefusesChangedHash`）
5. test-ext 的檢查失敗 → 失敗訊息只出現題號，不出現題目或 SQL，主 session 跑測試時不會看到 test 內容（Task 5：`testExtHeldoutGoldSqlRunsAndReturnsRows` 收集失敗的題號再斷言）

---

### Task 1: 舊題標準答案的 hash 快照

**Files:**
- Create: `evals/snapshot.py`、`evals/gold_snapshot.json`（由程式產生）
- Test: `tests/test_evals.py`

**Interfaces:**
- Produces:
  - `snapshotPath: Path`（`evals/gold_snapshot.json`）
  - `protectedCases() -> list[dict]`：這個 Task 回傳 `cases.cases + heldout_cases.heldoutCases`
  - `hashRows(rows: list[tuple]) -> str`：先 `scoring.normalizeRows`，再依 `repr` 排序，`json.dumps(..., default=str, ensure_ascii=False)` 後取 sha256 十六進位
  - `computeGoldHashes(databaseUrl: str, caseList: list[dict]) -> dict[str, list[str]]`：題號 → `[goldSql, *alsoAccept]` 每一句結果的 hash
  - `class SnapshotMismatchError(Exception)`，屬性 `changedIds: list[str]`
  - `mergeSnapshot(existing: dict, current: dict) -> dict`：兩邊都有的題號 hash 不同就丟 `SnapshotMismatchError`；否則回傳合併後、依題號排序的 dict
  - `main()`：在 `TEST_DATABASE_URL` 的暫時 schema 建 fixture，算 `protectedCases()` 的 hash，跟現有快照（沒有檔案就當空的）`mergeSnapshot` 後寫回；只印題數，不印 hash 以外的內容。`SnapshotMismatchError` 時印出題號並以非 0 結束

- [ ] **Step 1: 開分支並 commit 設計文件與計畫**

```bash
git checkout -b feat/realistic-schema
git add docs/superpowers/specs/2026-11-19-realistic-schema-design.md docs/superpowers/plans/2026-11-19-realistic-schema.md
git commit -m "新增「讓 text2sql 面對接近真實的結構」的設計文件與實作計畫"
```

- [ ] **Step 2: 寫失敗的測試**（`tests/test_evals.py`，`from evals import snapshot`）

```python
def testHashRowsIgnoresRowOrder():
  assert snapshot.hashRows([("早班", 1), ("晚班", 2)]) == snapshot.hashRows([("晚班", 2), ("早班", 1)])
  assert snapshot.hashRows([("早班",)]) != snapshot.hashRows([("晚班",)])


def testMergeSnapshotAddsNewIds():
  merged = snapshot.mergeSnapshot({"b01": ["aa"]}, {"b01": ["aa"], "h-org01": ["bb"]})

  assert merged == {"b01": ["aa"], "h-org01": ["bb"]}


def testMergeSnapshotRefusesChangedHash():
  with pytest.raises(snapshot.SnapshotMismatchError) as error:
    snapshot.mergeSnapshot({"b01": ["aa"], "b02": ["cc"]}, {"b01": ["zz"], "b02": ["cc"]})

  assert error.value.changedIds == ["b01"]


def testGoldAnswersMatchSnapshot(evalDatabaseUrl):
  # 只比 hash：失敗時只看得到題號，看不到 test 的答案內容
  saved = json.loads(snapshot.snapshotPath.read_text(encoding="utf-8"))

  assert snapshot.computeGoldHashes(evalDatabaseUrl, snapshot.protectedCases()) == saved
```

- [ ] **Step 3: 確認測試失敗**

Run: `python -m pytest tests/test_evals.py -q -k "HashRows or MergeSnapshot or MatchSnapshot"`
Expected: FAIL，`ImportError: cannot import name 'snapshot'`

- [ ] **Step 4: 實作 `evals/snapshot.py`**（介面見上）

- [ ] **Step 5: 在目前的 fixture 上產生快照**

Run: `python -m evals.snapshot`
Expected: 印出 `71 題`（或同義的題數訊息），產生 `evals/gold_snapshot.json`

- [ ] **Step 6: 跑全部測試**

Run: `python -m pytest -q`
Expected: 全部 PASS

- [ ] **Step 7: Commit**

```bash
git add evals/snapshot.py evals/gold_snapshot.json tests/test_evals.py
git commit -m "評測加上標準答案的 hash 快照，改結構時確認舊題答案沒變"
```

---

### Task 2: 步驟 0：固定 num_ctx，重建基準

**Files:**
- Modify: `text2sql.py`（`callOllama` 上方加常數、`options`）
- Modify: `README.md`（`## text2sql 評測` 底下新增一節）
- Test: `tests/test_text2sql.py`

**Interfaces:**
- Produces: `text2sql.ollamaNumCtx = 8192`

- [ ] **Step 1: 寫失敗的測試**

```python
def testCallOllamaFixesContextLength(monkeypatch, modelEnv):
  sent = {}

  def fakePost(url, json, timeout):
    sent.update(json)
    return makeOpenRouterResponse(200, {"message": {"role": "assistant", "content": "SELECT 1"}})

  monkeypatch.setattr(text2sql.requests, "post", fakePost)

  assert text2sql.callOllama([{"role": "user", "content": "問題"}]) == "SELECT 1"
  assert sent["options"] == {"temperature": 0, "num_ctx": 8192}
```

- [ ] **Step 2: 確認測試失敗**

Run: `python -m pytest tests/test_text2sql.py -q -k FixesContextLength`
Expected: FAIL，`options` 少了 `num_ctx`

- [ ] **Step 3: 實作**：`ollamaNumCtx = 8192`，`callOllama` 的 `options` 改成 `{"temperature": 0, "num_ctx": ollamaNumCtx}`。註解寫原因：沒設時預設值依 Ollama 版本而定，prompt 超過會被默默截掉；這個值影響分數，所以寫死在程式裡、不放 `.env`

- [ ] **Step 4: 跑全部測試**

Run: `python -m pytest -q`
Expected: 全部 PASS

- [ ] **Step 5: 確認 8192 放得進 GPU**

Run: `python -m evals.run --model qwen3-vl:4b-instruct --filter b01`，接著 `ollama ps`
Expected: `qwen3-vl:4b-instruct` 那列 PROCESSOR 是 `100% GPU`、CONTEXT 是 `8192`。不是 100% GPU 的話停下來問使用者，不要自己調小

- [ ] **Step 6: 截斷檢查**（之後步驟 1、2 會再跑；可以把這段存到 scratchpad 重複用）

先 `ollama stop qwen2.5:3b`、`ollama stop qwen3-vl:4b-instruct`（避免 prompt 快取讓 token 數偏低），再執行：

```python
import os, requests
from dotenv import load_dotenv
import db, text2sql
from evals import fixture
from evals.cases import cases
load_dotenv()
# 只從 dev 挑最長的題目：prompt 只有最後的問題會變，test 題不能拿出來
question = max((case["question"] for case in cases), key=len)
with db.temporarySchema(os.environ["TEST_DATABASE_URL"], "tokens") as url:
  fixture.buildDb(url)
  messages = text2sql.buildMessages(question, db.getLlmSchemaText(), db.getVocabulary(url), fixture.fixedNow)
for model in ["qwen2.5:3b", "qwen3-vl:4b-instruct"]:
  reply = requests.post(
    f"{text2sql.getOllamaConfig()['url']}/api/chat",
    json={"model": model, "messages": messages, "stream": False, "options": {"temperature": 0, "num_ctx": text2sql.ollamaNumCtx}},
    timeout=300,
  ).json()
  print(model, reply["prompt_eval_count"], "/", text2sql.ollamaNumCtx)
```

Expected: 兩個模型都小於 4096

- [ ] **Step 7: 重跑舊基準**（可以背景執行）

```bash
python -m evals.run --model qwen2.5:3b
python -m evals.run --model qwen2.5:3b --split test
python -m evals.run --model qwen3-vl:4b-instruct
python -m evals.run --model qwen3-vl:4b-instruct --split test
```

Expected: 四輪都沒有連線錯誤的提示。記下總分與 dev 各類別分數

- [ ] **Step 8: README 新增一節 `### 結構變複雜的代價（2026-11-19 起）`**，放在「和改成多對多之前比較」前面。內容：一句話說明這一節在量什麼（連到設計文件）、`num_ctx` 固定 8192 的原因、兩個模型的 `prompt_eval_count`，以及設計文件「交付」那張量測表（先填步驟 0 這一列，其他列留空）。另附 dev 各類別的表（欄位：類別、題數、步驟 0 的 3b、4b）。步驟 0 跟「加入靜態規則之後」的分數不同時，照實寫出差異，並註明之後以步驟 0 為基準

- [ ] **Step 9: Commit**

```bash
git add text2sql.py tests/test_text2sql.py README.md
git commit -m "Ollama 固定 num_ctx 8192，重跑基準分數"
```

---

### Task 3: 步驟 1：模型改看原始的三張表

**Files:**
- Modify: `llm_schema.sql`（整份重寫）
- Modify: `text2sql.py`（`buildMessages` 的規則 2、6、8、9、12、「目前資料中的值」、3 個 few-shot）
- Modify: `README.md`（「結構」表的 `llm_schema.sql` 一列、「資料結構」第一個項目、量測表）
- Test: `tests/test_db.py`、`tests/test_text2sql.py`

**Interfaces:**
- Consumes: Task 2 的量測方式
- Produces: `llm_schema.sql` 每張實體表一個 `CREATE TABLE <name> (...)` 區塊，列出該表所有欄位並附註解（Task 4 會照同樣格式加新表）

- [ ] **Step 1: 改寫測試**

`tests/test_db.py`：`testLlmSchemaHidesTheJoinTable` 換成下面這個

```python
def testLlmSchemaListsEveryRealColumn(databaseUrl):
  # 給模型看的說明是手寫的，實際的表多了欄位卻沒寫進去，模型就不知道它存在
  _, rows = db.runReadOnlyQuery(databaseUrl, """
    SELECT c.table_name, c.column_name
    FROM information_schema.columns c
    JOIN information_schema.tables t ON t.table_schema = c.table_schema AND t.table_name = c.table_name
    WHERE c.table_schema = current_schema() AND t.table_type = 'BASE TABLE'
  """)
  blocks = {block.split("(")[0].strip(): block for block in db.getLlmSchemaText().split("CREATE TABLE ")[1:]}

  assert "event_details" not in db.getLlmSchemaText()
  assert {table for table, _ in rows} == set(blocks)
  assert [(table, column) for table, column in rows if column not in blocks[table]] == []
```

`tests/test_text2sql.py`：
- `testPromptContainsDatesSchemaAndVocabulary`：`"CREATE TABLE event_details"` 改成 `"CREATE TABLE event_resources"`，再加 `assert "- resources.name：" in systemPrompt` 與 `assert "resource_name（resources.name）" not in systemPrompt`
- `testPromptTeachesModelToQueryTheFlatView` 換成：

```python
def testPromptTeachesModelToJoinRawTables(demoDatabaseUrl):
  messages = text2sql.buildMessages("問題", db.getLlmSchemaText(), db.getVocabulary(demoDatabaseUrl), fixedNow)
  systemPrompt = messages[0]["content"]
  fewShotSqls = getFewShotSqls(demoDatabaseUrl)

  # JOIN event_resources 之後一筆排程有多列，prompt 沒提醒的話模型會用 COUNT(*) 多算
  assert "COUNT(DISTINCT events.id)" in systemPrompt
  assert "event_details" not in systemPrompt
  assert len(fewShotSqls) == 3
  assert all("event_details" not in sql and "FROM events" in sql for sql in fewShotSqls)


viewVersionFewShotSqls = [
  "SELECT resource_name, title, start_at, end_at FROM event_details "
  "WHERE resource_name LIKE '%小明%' AND start_at::date = '2026-11-18' ORDER BY start_at",
  "SELECT COUNT(DISTINCT event_id) AS meeting_count FROM event_details "
  "WHERE category = 'meeting' AND start_at::date BETWEEN '2026-11-23' AND '2026-11-29'",
  "SELECT title, start_at, end_at FROM event_details WHERE resource_name LIKE '%李小華%' "
  "AND event_id IN (SELECT event_id FROM event_details WHERE resource_name LIKE '%陳大文%') ORDER BY start_at",
]


def testFewShotResultsMatchViewVersion(demoDatabaseUrl):
  # 改寫只換寫法不換意思：每個範例查出來的結果要跟改寫前的 view 版本一模一樣
  for newSql, viewSql in zip(getFewShotSqls(demoDatabaseUrl), viewVersionFewShotSqls, strict=True):
    _, viewRows = db.runReadOnlyQuery(demoDatabaseUrl, viewSql)
    assert viewRows
    assert db.runReadOnlyQuery(demoDatabaseUrl, newSql)[1] == viewRows
```

- [ ] **Step 2: 確認測試失敗**

Run: `python -m pytest tests/test_db.py tests/test_text2sql.py -q -k "LlmSchemaListsEveryRealColumn or PromptContainsDates or JoinRawTables or MatchViewVersion"`
Expected: FAIL（schema 說明裡還有 `event_details`、prompt 裡沒有 `COUNT(DISTINCT events.id)`）

- [ ] **Step 3: 重寫 `llm_schema.sql`**：`events`（id、title、category、start_at、end_at、note）、`event_resources`（event_id、resource_id、position）、`resources`（id、name、type、note），沿用現在的註解風格（例子、category 與 type 的值）。開頭用兩三行說明三張表怎麼對應，以及「一筆排程有幾個資源，event_resources 就有幾列」。不提 view

- [ ] **Step 4: 改寫 `buildMessages`**（以下是確切的新文字）

| 位置 | 新文字 |
|---|---|
| 規則 2 | `2. 只能使用下方 schema 裡的資料表與欄位。排程在 events，資源在 resources，兩者透過 event_resources 對應；同時用到排程和資源時，JOIN 這三張表。` |
| 規則 6 | `6. 列出排程時帶出資源名稱（resources.name），並依 start_at 排序，讓結果看得懂。` |
| 規則 8 | `8. 「人」「每個人」「員工」「誰」指 resources.type = 'person'；「會議室」指 'room'；「設備」指 'equipment'。` |
| 規則 9 | `9. JOIN event_resources 之後，一筆排程有幾個資源就有幾列。計算「幾筆排程」「幾場會議」時用 COUNT(DISTINCT events.id)，不要用 COUNT(*)。` |
| 規則 12 | `12. 同一筆排程的每個資源在 event_resources 裡都有相同的 event_id。要找兩個資源一起參與的排程（例如某人在某間會議室開的會），用 events.id IN (SELECT event_resources.event_id FROM event_resources JOIN resources ON resources.id = event_resources.resource_id WHERE ...) 子查詢。` |
| 目前資料中的值 | `- events.category：…`、`- resources.type：…`、`- resources.name：…`（值的來源不變） |

few-shot 的問題與順序不變，SQL 照這個原則機械式改寫：`event_details` 換成「只用到排程欄位時只查 `events`；用到資源時 JOIN 三張表」，欄位一律寫完整表名（`events.title`、`resources.name`），不用別名，跟規則的寫法一致；其他部分（選的欄位、條件、ORDER BY、`COUNT(DISTINCT ...)`）照原樣。第 2 個範例因此是 `SELECT COUNT(DISTINCT events.id) AS meeting_count FROM events WHERE events.category = 'meeting' AND ...`

- [ ] **Step 5: 跑全部測試**

Run: `python -m pytest -q`
Expected: 全部 PASS（`testGoldAnswersMatchSnapshot` 也要過）

- [ ] **Step 6: 確認只動了該動的規則**

Run: `git diff HEAD -- text2sql.py`（HEAD 是 Task 2 的 commit，所以不會混進 `num_ctx` 的改動）
Expected: 只有規則 2、6、8、9、12、「目前資料中的值」三行與 few-shot 的 SQL 有差異

- [ ] **Step 7: 截斷檢查**：照 Task 2 Step 6 再跑一次，兩個模型都小於 4096

- [ ] **Step 8: 量測**：照 Task 2 Step 7 跑四輪

- [ ] **Step 9: 整理錯誤模式**：只比對兩個模型「步驟 0」和「步驟 1」的 dev 報告（`evals/results/<模型>-dev-*.json`），列出變錯、變對的題號，看模型寫的 SQL 歸納出新的錯誤類型（例如漏掉 event_resources、JOIN 之後用 COUNT(*) 重複計算、還在用 `resource_name` 這類 view 的欄位、自己加的別名跟規則寫法不一致）。不針對這些錯誤改 prompt

- [ ] **Step 10: 更新 README**：量測表填「步驟 1」這一列；記下 Step 7 的 `prompt_eval_count`；dev 各類別表加上步驟 1 的欄位；Step 9 的錯誤模式寫成條列，每類附題號與數量；「結構」表的 `llm_schema.sql` 改成「寫給 text2sql 模型看的結構說明：原始資料表與欄位註解，不含 view」；「資料結構」第一個項目改成：模型看的是原始的表，要自己 JOIN；`event_details` 留在資料庫裡，是舊的標準答案在用

- [ ] **Step 11: Commit**

```bash
git add llm_schema.sql text2sql.py tests/test_db.py tests/test_text2sql.py README.md
git commit -m "text2sql 改看原始的三張表，照 view 寫的規則與範例改寫成 JOIN 版本"
```

---

### Task 4: 步驟 2：新增 6 張表與資料

**Files:**
- Modify: `schema.sql`（檔案最後加 6 張表）、`llm_schema.sql`（加 6 個區塊）
- Modify: `db.py`（新增 `addOrganizationData`，修改 `seedDemoData`、`getVocabulary`）
- Modify: `text2sql.py`（「目前資料中的值」加 3 行）
- Modify: `evals/fixture.py`（新增資料、`buildDb`）
- Modify: `README.md`（「資料結構」表、「執行」）
- Test: `tests/test_db.py`、`tests/test_evals.py`、`tests/test_text2sql.py`

**Interfaces:**
- Consumes: Task 3 的 `llm_schema.sql` 區塊格式與 `testLlmSchemaListsEveryRealColumn`（會自動檢查新表）
- Produces:
  - 6 張表：照設計文件「步驟 2」的 SQL，每句改成 `CREATE TABLE IF NOT EXISTS`（app 每次啟動都會執行 `schema.sql`）
  - `db.addOrganizationData(databaseUrl: str, data: dict) -> None`：一個交易寫完；資源、部門、主管用名稱對應，找不到名稱就丟 `ValueError` 並整筆不寫入。`data` 的鍵與每一列的格式：
    - `"departments"`：`(name, parentName | None)`，上層部門要排在前面
    - `"employees"`：`(personName, departmentName, jobTitle, managerName | None, "YYYY-MM-DD")`，主管要排在前面
    - `"rooms"`：`(roomName, floor, capacity, hasVideoConference)`
    - `"workHours"`：`(personName, weekday, "HH:MM", "HH:MM")`
    - `"leaveRequests"`：`(personName, leaveType, "YYYY-MM-DD HH:MM", "YYYY-MM-DD HH:MM", status)`
    - `"holidays"`：`("YYYY-MM-DD", name)`
  - `db.getVocabulary` 多回傳 `departmentNames`、`leaveTypes`、`leaveStatuses`（各自 `SELECT DISTINCT ... ORDER BY`）
  - prompt「目前資料中的值」在 `resources.name` 那行後面加：`- departments.name：…`、`- leave_requests.leave_type：…`、`- leave_requests.status：…`
  - `evals/fixture.py` 新增模組常數 `organization`（格式同上），`buildDb` 建完排程後呼叫 `db.addOrganizationData(databaseUrl, organization)`

**fixture 的新資料**（`evals/fixture.py`）：

| 表 | 資料 |
|---|---|
| departments | 總經理室（無上層）、業務部（上層 總經理室）、營運部（上層 總經理室） |
| employees | 王小明：總經理室、副總經理、無主管、2019-03-01；李小華：營運部、營運組長、主管 王小明、2021-07-15；林美玲：業務部、門市專員、主管 王小明、2024-09-02；陳大文：營運部、值班專員、主管 李小華、2023-02-01 |
| rooms | A 會議室：10 樓、12 人、有視訊；B 會議室：8 樓、6 人、沒有視訊 |
| work_hours | 王小明：星期一到五（1–5）09:00–18:00 |
| leave_requests | 王小明 annual 2026-11-20 09:00–18:00 approved；陳大文 sick 2026-11-25 00:00–2026-11-27 00:00 approved；林美玲 personal 2026-11-18 13:00–17:00 approved；李小華 annual 2026-11-23 08:00–16:00 rejected（跟早班重疊）；陳大文 personal 2026-11-30 00:00–2026-12-01 00:00 pending |
| holidays | 2026-11-11 公司創立紀念日；2026-12-25 行憲紀念日；2027-01-01 開國紀念日 |

2026-12-25 要先查人事行政總處公告的 2026 年辦公日曆表，確認是放假日；不是的話刪掉這一筆，其他照舊。

**示範資料的新資料**（`db.seedDemoData`，日期以本週一 `monday` 為基準）：部門同 fixture；員工只有王小明、李小華、陳大文，部門、職稱、主管同 fixture；會議室同 fixture；work_hours 同 fixture；假日同 fixture；請假：王小明 annual `monday+11` 09:00–18:00 approved、陳大文 sick `monday+2` 00:00–`monday+4` 00:00 approved、李小華 personal `monday+8` 08:00–16:00 rejected、李小華 annual `monday+12` 00:00–`monday+13` 00:00 pending。

- [ ] **Step 1: 寫失敗的測試**

`tests/test_db.py`：
- `testAddOrganizationDataLinksPeopleDepartmentsAndRooms`：先 `addResource` 兩個 person、一個 room，寫入兩個部門（一個有上層）、兩個員工（一個的主管是另一個）、一間會議室；斷言用 SQL JOIN 查得到「下屬名字、主管名字、下屬部門的上層部門名稱」，`rooms` 有那一間
- `testAddOrganizationDataRejectsUnknownResourceAndSavesNothing`：`employees` 寫一個不存在的名字，`pytest.raises(ValueError)`；之後 `departments` 與 `employees` 都是 0 筆
- `testSeedDemoDataFillsOrganizationTables`：`seedDemoData(databaseUrl, today=day)` 後，筆數 departments 3、employees 3、rooms 2、work_hours 5、leave_requests 4、holidays ≥ 2
- `testDemoApprovedLeaveDoesNotOverlapOwnEvents`：見下方的重疊查詢，結果 0 筆
- `testInitDbTwiceKeepsDemoData`：`seedDemoData` 後再 `initDb`，不報錯，`employees` 仍是 3 筆

`tests/test_evals.py`（用 `evalDatabaseUrl`）：
- `testFixtureOrganizationDescribesOnlyExistingResources`：`employees` 4 筆且對應的 `resources.type` 全是 `person`；`rooms` 2 筆且全是 `room`
- `testFixtureOrganizationHasTwoLevelsOfManagers`：恰好 1 個員工 `manager_id IS NULL`；`employees e JOIN employees m ON m.id = e.manager_id WHERE m.manager_id IS NOT NULL` 至少 1 筆；部門 3 個，其中 2 個的 `parent_id` 指向唯一沒有上層的那個
- `testFixtureRoomsDiffer`：`COUNT(DISTINCT floor)`、`COUNT(DISTINCT capacity)`、`COUNT(DISTINCT has_video_conference)` 都是 2
- `testFixtureLeaveRequestsCoverEveryStatusAndType`：status 集合 `{"pending", "approved", "rejected"}`、leave_type 集合 `{"annual", "sick", "personal"}`；至少一筆 `end_at::date > start_at::date`；至少一筆 `end_at - start_at <= interval '4 hours'`
- `testFixtureApprovedLeaveDoesNotOverlapOwnEvents`：重疊查詢 0 筆
- `testFixtureWorkHoursOnlyForStaffWithoutShifts`：有 `work_hours` 的員工，在 `events` 裡沒有任何 `category = 'shift'` 的排程
- `testFixtureHolidays`：至少一個假日落在 2026-11-09～2026-11-28 之間，而且那天沒有任何排程；至少一個假日在 2026-11-28 之後

重疊查詢（兩個檔案共用同一句，放在其中一個測試檔的模組常數或各自寫一份皆可）：

```sql
SELECT l.id FROM leave_requests l
JOIN employees em ON em.id = l.employee_id
JOIN event_resources er ON er.resource_id = em.resource_id
JOIN events e ON e.id = er.event_id
WHERE l.status = 'approved' AND e.start_at < l.end_at AND e.end_at > l.start_at
```

`tests/test_text2sql.py`：
- `testPromptListsOrganizationVocabulary(demoDatabaseUrl)`：system prompt 含 `- departments.name：`、`營運部`、`- leave_requests.status：`、`approved`

- [ ] **Step 2: 確認測試失敗**

Run: `python -m pytest -q -k "Organization or DemoApproved or InitDbTwice or FixtureRooms or FixtureLeave or FixtureApproved or FixtureWorkHours or FixtureHolidays or OrganizationVocabulary"`
Expected: FAIL（`relation "employees" does not exist` 或 `AttributeError: ... addOrganizationData`）

- [ ] **Step 3: 實作**：`schema.sql` 加表、`db.addOrganizationData`、`seedDemoData` 呼叫它、`getVocabulary`、prompt 的 3 行、`fixture.organization` 與 `buildDb`

- [ ] **Step 4: `llm_schema.sql` 加 6 個區塊**：照 Task 3 的格式。註解要寫出設計文件 SQL 裡的語意：employees 對應 person 資源、rooms 對應 room 資源、weekday 1 = 星期一且與 `EXTRACT(ISODOW FROM ...)` 相同、輪班員工沒有 work_hours（上班時間看 events 的 shift）、只有 `status = 'approved'` 的才算請假、請假可以跨好幾天、leave_type 與 status 各值的中文意思

- [ ] **Step 5: 跑全部測試**

Run: `python -m pytest -q`
Expected: 全部 PASS，特別是 `testGoldAnswersMatchSnapshot`、`testFixtureBuildsFixedDataset`、`testLlmSchemaListsEveryRealColumn`

- [ ] **Step 6: 更新 README**：「資料結構」表加 6 張新表各一列；「執行」的步驟加一條：從這一版之前的版本更新時，先 `docker compose down -v` 清空重建，新表才會有示範資料（`seedDemoData` 只在資料庫是空的時候執行）

- [ ] **Step 7: Commit**

```bash
git add schema.sql llm_schema.sql db.py text2sql.py evals/fixture.py tests/ README.md
git commit -m "新增部門、員工、會議室細節、上班時段、請假、假日六張表與固定資料"
```

---

### Task 5: test-ext：全新 subagent 出題，使用者抽查後凍結

**Files:**
- Create: `evals/ext_cases.py`（這個 Task 只放類別）
- Create: `evals/ext_heldout_cases.py`（由 subagent 寫，主 session 不讀）
- Modify: `evals/snapshot.py`（`protectedCases` 加上 test-ext）、`evals/gold_snapshot.json`
- Test: `tests/test_evals.py`

**Interfaces:**
- Produces:
  - `evals/ext_cases.py`：`extCategories = ["org", "room", "hours", "leave", "combo"]`、`extCases = []`（Task 6 填入）；模組說明寫出設計文件「新的評測集」那張類別表
  - `evals/ext_heldout_cases.py`：`extHeldoutCases: list[dict]`，15 題，每類 3 題，題號 `h-org01`～`h-org03`、`h-room01`…`h-combo03`，格式同 `evals/cases.py`（`id`、`category`、`question`、`goldSql`，選用 `compareAsSet`、`alsoAccept`）
  - `snapshot.protectedCases()` 回傳 `cases.cases + heldout_cases.heldoutCases + ext_heldout_cases.extHeldoutCases`

- [ ] **Step 1: 建立 `evals/ext_cases.py`**（只有類別與說明）

- [ ] **Step 2: 寫測試**（`tests/test_evals.py`）。失敗訊息只能出現題號：

```python
def testExtHeldoutCasesAreWellFormed():
  heldout = ext_heldout_cases.extHeldoutCases
  oldQuestions = {case["question"] for case in allCases}

  assert len({case["id"] for case in heldout}) == len(heldout) == 15
  assert [case["id"] for case in heldout if not case["id"].startswith("h-")] == []
  assert Counter(case["category"] for case in heldout) == {category: 3 for category in ext_cases.extCategories}
  # 只列題號：題目文字印出來就等於讓主 session 看到 test
  assert [case["id"] for case in heldout if case["question"] in oldQuestions] == []


def testExtHeldoutGoldSqlRunsAndReturnsRows(evalDatabaseUrl):
  failedIds = []
  for case in ext_heldout_cases.extHeldoutCases:
    try:
      for sql in [case["goldSql"], *case.get("alsoAccept", [])]:
        text2sql.validateSql(sql)
        if not db.runReadOnlyQuery(evalDatabaseUrl, sql)[1]:
          raise ValueError
    except Exception:
      # 錯誤訊息可能帶出 SQL，只記題號
      failedIds.append(case["id"])

  assert failedIds == []
```

另外把 `testCasesDoNotReuseFewShotQuestions` 的比對範圍加上 test-ext，同樣改成只斷言題號清單為空。`allCases`（用在逐題參數化的測試）**不要**加入 test-ext，參數化的失敗訊息會帶出 SQL。

- [ ] **Step 3: 確認測試失敗**

Run: `python -m pytest tests/test_evals.py -q -k ExtHeldout`
Expected: FAIL，`ImportError`（`ext_heldout_cases` 不存在）

- [ ] **Step 4: 派一個全新的 subagent 出題**（general-purpose），prompt 如下，不要加入任何 dev 題目或評測結果：

```
你要替一個 text2sql 評測集出 15 題 test 題。這些題目之後不會給調 prompt 的人看，所以你的回報裡不能出現任何題目文字或 SQL。

專案在 D:\machine learning\schedule-mvp。只讀這些檔案：schema.sql、llm_schema.sql、evals/fixture.py、evals/scoring.py、evals/ext_cases.py，以及 evals/cases.py 第 1–17 行（出題原則）。不要讀 README.md、docs/、evals/heldout_cases.py、evals/results/，也不要讀 evals/cases.py 第 17 行以後。

寫 evals/ext_heldout_cases.py，定義 extHeldoutCases（list of dict），格式：{"id", "category", "question", "goldSql"}，可選 "compareAsSet": True 與 "alsoAccept": [SQL...]，用法照 cases.py 開頭的出題原則。
- 5 個類別各 3 題，類別與要測的東西見 evals/ext_cases.py 的說明；題號 h-org01～h-org03、h-room01…、h-hours01…、h-leave01…、h-combo01…
- 「現在」是 2026-11-17（二）14:30；本週 11-16～11-22、上週 11-09～11-15、下週 11-23～11-29
- 題目用台灣慣用的口語中文，像真的使用者會問的問題；每題都要至少用到一張新表（departments、employees、rooms、work_hours、leave_requests、holidays）
- 每題的標準答案 SQL 都要實際在 fixture 上跑過，結果非空，而且你確認結果確實回答了問題
- 難度要有高有低：多層 JOIN、主管與上層部門（自己參照）、請假的時間區間重疊、只算核准的假、多張表都有 name 欄位、上班時段與假日

測試資料庫：.env 的 TEST_DATABASE_URL；可以用 db.temporarySchema + evals.fixture.buildDb 建一份來試 SQL。
寫完執行：python -m pytest tests/test_evals.py -q -k "ExtHeldout or FewShot"，全部要通過。

回報只寫：各類別題數、測試是否全部通過。不要寫題目、SQL 或答案。
```

- [ ] **Step 5: 主 session 跑測試**

Run: `python -m pytest -q`
Expected: 全部 PASS（`-q` 通過時不會印出題目內容）

- [ ] **Step 6: 停下來請使用者抽查**：請使用者打開 `evals/ext_heldout_cases.py`，對照 `evals/fixture.py` 檢查每題的標準答案。使用者發現錯誤時，由使用者自己改，或由使用者說明要改什麼，再派一個全新的 subagent 去改（同樣的限制與回報規則）。**等使用者確認後才往下做**

- [ ] **Step 7: 快照加入 test-ext**：`protectedCases()` 加上 `extHeldoutCases`，執行 `python -m evals.snapshot`
Expected: 新增 15 題，沒有出現 `SnapshotMismatchError`

- [ ] **Step 8: 跑全部測試**

Run: `python -m pytest -q`
Expected: 全部 PASS

- [ ] **Step 9: 凍結 commit**（不要先看 diff）

```bash
git add evals/ext_cases.py evals/ext_heldout_cases.py evals/snapshot.py evals/gold_snapshot.json tests/test_evals.py
git commit -m "新增新表的 test-ext 15 題並凍結，標準答案加入 hash 快照"
```

---

### Task 6: dev-ext 25 題與評測的新 split

**Files:**
- Modify: `evals/ext_cases.py`（填 `extCases`）
- Modify: `evals/run.py`
- Modify: `evals/fixture.py`（只有 dev-ext 需要時才加資料）
- Test: `tests/test_evals.py`

**Interfaces:**
- Consumes: Task 5 的 `extCategories`、`extHeldoutCases`
- Produces:
  - `evals/run.py`：`casesBySplit` 加 `"dev-ext": extCases`、`"test-ext": extHeldoutCases`；`hiddenSplits = {"test", "test-ext"}`，原本 `args.split == "test"` 的兩個判斷（不能搭配 `--filter`、只印進度）改成 `in hiddenSplits`；`--split` 的說明補上兩個新選項
  - `extCases`：25 題，每類 5 題，題號 `e-org01`～`e-combo05`

- [ ] **Step 1: 寫失敗的測試**

```python
def testExtCasesAreWellFormed():
  heldoutQuestions = {case["question"] for case in ext_heldout_cases.extHeldoutCases}
  # 不能用 allCases：這個 Task 會把 extCases 加進 allCases，每題都會跟自己重複
  oldQuestions = {case["question"] for case in cases.cases + heldout_cases.heldoutCases}

  assert len({case["id"] for case in ext_cases.extCases}) == len(ext_cases.extCases) == 25
  assert all(case["id"].startswith("e-") for case in ext_cases.extCases)
  assert Counter(case["category"] for case in ext_cases.extCases) == {category: 5 for category in ext_cases.extCategories}
  # 只列題號，不印出 test-ext 的題目
  assert [case["id"] for case in ext_cases.extCases if case["question"] in heldoutQuestions] == []
  assert [case["id"] for case in ext_cases.extCases if case["question"] in oldQuestions] == []


@pytest.mark.parametrize("split", ["test", "test-ext"])
def testMainHiddenSplitsHidePerCaseResults(tmp_path, capsys, split):
  evalRun.main(["--split", split, "--model", "fake:1b", "--out", str(tmp_path)], llm=lambda messages: "SELECT 1")

  output = capsys.readouterr().out
  assert "FAIL" not in output
  assert "SELECT 1" not in output


@pytest.mark.parametrize("split", ["test", "test-ext"])
def testMainRejectsFilterOnHiddenSplits(tmp_path, split):
  with pytest.raises(SystemExit):
    evalRun.main(["--split", split, "--filter", "org", "--out", str(tmp_path)], llm=answerWithGoldSql)


def testMainDevExtPassesEveryCaseWithGoldAnswers(tmp_path):
  summary = evalRun.main(["--split", "dev-ext", "--out", str(tmp_path)], llm=answerWithGoldSql)

  assert summary["passed"] == summary["total"] == 25


def testMainTestExtPassesEveryCaseWithGoldAnswers(tmp_path):
  summary = evalRun.main(["--split", "test-ext", "--out", str(tmp_path)], llm=answerWithGoldSql)

  assert summary["passed"] == summary["total"] == 15
```

`extCases` 也加進 `allCases`（dev 題可以逐題參數化）。`answerWithGoldSql` 的查表改成 `allCases + ext_heldout_cases.extHeldoutCases`，否則 test-ext 的題目查不到，`KeyError` 還會把題目文字印出來。現有的 `testMainTestSplitHidesPerCaseResults`、`testMainRejectsFilterOnTestSplit` 由上面兩個參數化測試取代。

- [ ] **Step 2: 確認測試失敗**

Run: `python -m pytest tests/test_evals.py -q -k "ExtCases or HiddenSplits or DevExt or TestExt"`
Expected: FAIL（`extCases` 是空的、`--split dev-ext` 不是合法選項）

- [ ] **Step 3: 實作 `evals/run.py` 的新 split**

- [ ] **Step 4: 出 dev-ext 25 題**：照 `evals/cases.py` 開頭的出題原則，每類 5 題，涵蓋設計文件列的難點：多層 JOIN（人 → 員工 → 部門）、主管與上層部門（自己參照）、請假區間重疊、只算核准的假、多張表都有 `name`、`weekday` 與 `EXTRACT(ISODOW ...)`、假日、沒有員工的部門（總經理室以外）。每題的標準答案先在 fixture 上跑過，確認結果回答了問題。需要加 fixture 資料時可以加在新表，但 `testGoldAnswersMatchSnapshot` 必須通過

- [ ] **Step 5: 跑全部測試**

Run: `python -m pytest -q`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add evals/ext_cases.py evals/run.py evals/fixture.py tests/test_evals.py
git commit -m "新增新表的 dev-ext 25 題，評測可以選 dev-ext 與 test-ext"
```

---

### Task 7: 步驟 2 量測與 README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 截斷檢查**：照 Task 2 Step 6，但題目改成從 `cases` 與 `ext_cases.extCases` 合起來挑最長的一題。兩個模型都小於 4096

- [ ] **Step 2: 量測**：兩個模型各跑 `dev`、`test`、`dev-ext`、`test-ext` 四個 split，共 8 輪

- [ ] **Step 3: 整理錯誤模式**：只看 dev 與 dev-ext 的報告。dev 比對步驟 1 與步驟 2，列出因為表變多而變錯的題號與 SQL 錯誤類型；dev-ext 依類別歸納錯誤類型（例如 `start_at` 在 events 與 leave_requests 都有而造成欄位不明確、忘了篩 `status = 'approved'`、weekday 編號用錯、自己參照的 JOIN 方向寫反）。不針對這些錯誤改 prompt

- [ ] **Step 4: 更新 README**
  - 量測表填完「步驟 2」兩列；記下 Step 1 的 `prompt_eval_count`；dev 各類別表加步驟 2；新增 dev-ext 各類別表
  - Step 3 的錯誤模式，跟 Task 3 的寫在同一節
  - 「text2sql 評測」的說明加上：`--split dev-ext`、`--split test-ext` 的用法；test-ext 由沒看過 dev 錯誤模式的 subagent 出題、使用者抽查後在哪一天凍結；`evals/gold_snapshot.json` 鎖住舊題與 test-ext 的答案；test-ext 只有 15 題，一題約 6.7 個百分點
  - 「目前限制」視情況補上這一輪觀察到的限制

- [ ] **Step 5: 跑全部測試**

Run: `python -m pytest -q`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "README 記錄新表的量測結果與錯誤模式"
```

- [ ] **Step 7: 請使用者確認 app**：先問使用者能不能執行 `docker compose down -v`（會刪掉整個資料庫，包含 `schedule_test`），同意後執行 `docker compose down -v` 與 `docker compose up -d --build --wait`。請使用者打開 http://127.0.0.1:8501 ，在「自然語言查詢」問「營運部有哪些人？」，應該看到李小華、陳大文
