# Jev 選工具正確率 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增只呼叫 Jev 的選工具評測，用它調 `jevCriteria`，讓「幾場會議」這類題目選 `run_sql`，再用完整評測確認 Haiku jev 分數。

**Architecture:** `evals/route_labels.py` 放 dev 每題可接受的工具；`evals/route.py` 對 dev 每題呼叫 `jev.chooseTool`（不開資料庫、不呼叫 LLM），比對標籤、印出逐題結果並存檔。調說明只改 `app/modules/qa/jev.py` 的 `jevCriteria`。

**Tech Stack:** Python 3、pytest、httpx（既有的 `jev.chooseTool`）

**Spec:** `docs/superpowers/specs/2026-11-23-jev-routing-design.md`

## Global Constraints

- 縮排 2 個空白；變數與函式用 camelCase；註解用正體中文，只說明「為什麼」。
- 只用 dev：`evals/route.py` 只匯入 `evals.cases`，不匯入、不打開 `evals/heldout_cases.py`。test 只能透過既有的 `python -m evals.run --split test` 看總分。
- 不改 `prompt.buildAgentMessages`、`tools.toolDefinitions`、`evals/scoring.py`、`jev.defaultMinConfidence`。
- `jevCriteria` 只描述「哪一類問題」，不能寫進 dev 題目的字句或人名（例如「林小美」「下週有幾場」）。
- 每次呼叫 Jev 或雲端模型之前，先給使用者估價、取得同意；Jev 的價格是每百萬輸入 token US$0.042，輸出免費。
- Jev 的 key 只從 `.env` 的 `JEV_API_KEY` 讀，不寫進程式或結果檔。
- 開始前從 main 建立分支 `feature/jev-routing`；各 Task 的 commit 都在這個分支上，不推送。

## Review Focus

1. 跑到一半 Jev 連不上（`chooseTool` 回傳 `fallbackReason="unavailable"`）：這種題不能當成「說明寫得不好」，總結要另外算 `unavailable`，並印出警告。→ Task 1 的 `testUnavailableCountedSeparately`
2. 之後有人在 `cases.py` 新增 dev 題卻沒加標籤：要直接失敗，不能默默略過。→ Task 1 的 `testLabelsCoverEveryDevCase`
3. Jev 沒回傳 token 數（`promptTokens=None`）：估價要當成 0，不能讓整輪當掉。→ Task 1 的 `testSummaryToleratesMissingTokens`
4. 沒設 `JEV_API_KEY` 就執行：要給清楚的訊息並結束，不能每題都退回、印出 0/40。→ Task 1 的 `testMainWithoutKeyExits`
5. 結果檔要看得出是哪一版說明跑的，否則幾輪下來分不清。→ Task 1 的 `testSummaryHasCriteriaHash`

---

### Task 1: 選工具評測

**Files:**
- Create: `backend/evals/route_labels.py`
- Create: `backend/evals/route.py`
- Test: `backend/tests/evals/test_route.py`

**Interfaces:**
- Consumes: `jev.chooseTool(question: str, now: datetime) -> JevDecision`（`tool`、`confidence`、`fallbackReason`、`promptTokens`、`seconds`）、`jev.jevOptions`、`jev.jevCriteria`、`jev.isConfigured()`、`jev.getJevConfig()["model"]`、`evals.cases.cases`、`evals.fixture.fixedNow`、`app.config.loadEnvFile()`
- Produces:
  - `route_labels.acceptableTools: dict[str, frozenset[str]]`
  - `route.routeCase(case: dict, chooseTool=jev.chooseTool, now: datetime = fixedNow) -> dict`，key 有 `id`、`question`、`acceptable`（排序過的 list）、`routeTool`、`confidence`、`fallback`、`correct`（bool）、`promptTokens`、`seconds`
  - `route.criteriaHash() -> str`：`json.dumps(jev.jevCriteria, ensure_ascii=False, sort_keys=True)` 的 sha256 取前 8 碼
  - `route.summarizeRoutes(results: list[dict]) -> dict`，key 有 `split`（固定 `"dev"`）、`jevModel`、`criteriaHash`、`total`、`correct`、`fallbacks`、`unavailable`、`wrongIds`、`promptTokens`、`estimatedUsd`、`finishedAt`、`results`
  - `route.main(argv=None, chooseTool=None) -> None`，執行方式：在 `backend/` 下跑 `python -m evals.route`

**標籤**（依過去所有 dev agent／jev 紀錄中「只用一個工具就答對過」的工具；s02 用 `find_available_people` 答對 2 次是巧合，因為那個工具不知道班別，所以不列入）：

| 可接受的工具 | 題號 |
|---|---|
| `find_available_people` | a01、a07 |
| `get_busy_periods` | a03、a04、a05、m07 |
| `get_busy_periods`、`run_sql` | a02、m01 |
| `run_sql` | 其餘 32 題（o01–o05、s01–s08、a06、l01–l08、m02–m06、g01–g05） |

- [ ] **Step 1: 寫會失敗的測試** `backend/tests/evals/test_route.py`（假的 `chooseTool` 回傳 `JevDecision`，不連網路）

```python
def testLabelsCoverEveryDevCase():
  assert set(acceptableTools) == {case["id"] for case in devCases}
  assert all(tools and tools <= set(jev.jevOptions) for tools in acceptableTools.values())

def testLabelCounts():
  assert acceptableTools["m02"] == {"run_sql"}
  assert acceptableTools["a02"] == {"get_busy_periods", "run_sql"}
  assert sum(tools == {"run_sql"} for tools in acceptableTools.values()) == 32

def testRouteCaseCorrect():          # o01、run_sql、0.9 → correct is True、confidence == 0.9
def testRouteCaseWrongTool():        # m02、get_busy_periods → correct is False、acceptable == ["run_sql"]
def testRouteCaseFallbackIsNotCorrect():  # tool=None、fallbackReason="low_confidence" → correct is False、fallback == "low_confidence"
def testRouteCasePassesFixedNow():   # 假 chooseTool 記下參數 → question == case["question"]、now == fixedNow
def testUnavailableCountedSeparately():   # 3 題，其中 1 題 fallback="unavailable" → summary["unavailable"] == 1、summary["fallbacks"] == 1
def testSummaryToleratesMissingTokens():  # promptTokens 一題 700、一題 None → summary["promptTokens"] == 700
def testSummaryEstimatesCost():      # promptTokens 合計 1_000_000 → estimatedUsd == 0.042
def testSummaryHasCriteriaHash():    # len == 8、全是十六進位、連續呼叫兩次相同
def testMainWithoutKeyExits(monkeypatch, capsys):  # jev.isConfigured → False → SystemExit code 1、stderr 含 "JEV_API_KEY"
def testMainRunsEveryDevCaseAndSaves(monkeypatch, tmp_path):  # 假 chooseTool、resultsDir 指到 tmp_path → 存一個 route-dev-*.json，results 的 id 依序等於 dev 題號
```

- [ ] **Step 2: 執行測試，確認失敗**

Run: `cd backend; python -m pytest tests/evals/test_route.py -v`
Expected: FAIL（`ModuleNotFoundError: evals.route_labels`）

- [ ] **Step 3: 實作 `route_labels.py` 與 `route.py`**

- `main`：用 `app.config.loadEnvFile()` 讀 `.env`。不要用 `evals.fixture.loadEnv`，它會要求設定資料庫，但這裡用不到資料庫。`jev.isConfigured()` 是 False 時，印出「請在 .env 填 JEV_API_KEY」到 stderr，然後 `SystemExit(1)`。
- 逐題印出一行：`✅ o01 run_sql（0.99）`、`❌ m02 get_busy_periods（0.80），可接受：run_sql`、`↩️ s05 退回（unavailable）`。最後一行印 `選對 N/40、退回 K 題（連不上 U 題）、Jev 輸入 T tokens、約 US$X、說明版本 <hash>`；`U > 0` 時多印一行警告，提醒這輪不能拿來比較。
- 存到 `evals/results/route-dev-<YYYYmmdd-HHMMSS>.json`。模組層級設 `resultsDir = run.resultsDir`，測試 monkeypatch `route.resultsDir`；`ensure_ascii=False`、`indent=2`。
- `estimatedUsd = round(promptTokens * 0.042 / 1_000_000, 4)`

- [ ] **Step 4: 執行測試，確認通過**

Run: `cd backend; python -m pytest tests/evals/test_route.py tests/qa/test_jev.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/evals/route_labels.py backend/evals/route.py backend/tests/evals/test_route.py docs/superpowers/specs/2026-11-23-jev-routing-design.md docs/superpowers/plans/2026-11-23-jev-routing.md
git commit -m "評測：新增只呼叫 Jev 的選工具評測"
```

---

### Task 2: 量基準並調 `jevCriteria`

**Files:**
- Modify: `backend/app/modules/qa/jev.py`（只改 `jevCriteria` 與上方註解）
- Modify: `backend/tests/qa/test_jev.py`（`testCriteriaPutConfusableWordsUnderRunSql`）
- Modify: `docs/superpowers/specs/2026-11-23-jev-routing-design.md`（新增「實測紀錄」一節）

**Interfaces:**
- Consumes: Task 1 的 `python -m evals.route`
- Produces: 新的 `jevCriteria`（三個 key 不變，順序同 `jevOptions`）

- [ ] **Step 1: 取得同意**：最多跑 8 輪（含基準），每輪約 28k tokens，約 US$0.0012，合計約 US$0.01。使用者同意後才呼叫 Jev。

- [ ] **Step 2: 量基準**

Run: `cd backend; python -m evals.route`
Expected: 印出 40 行與總結。依 README 記錄的離線檢查，預期約 39/40，只錯 m02。實際數字寫進「實測紀錄」，包含說明的 hash 與錯的題號。

- [ ] **Step 3: 改寫說明，一次改一個想法**。方向：`get_busy_periods` 強調「列出某段時間的行程明細（什麼時候、什麼事）」；「幾場、多少場」這類計數只放在 `run_sql`。說明要寫成一般的分類，不能用 dev 題目的字句。

- [ ] **Step 4: 每改一版跑一次** `python -m evals.route`，把 hash、選對數、錯的題號、跟上一版相比變對與變錯的題目寫進「實測紀錄」。一版要同時符合下面三個條件才算進步：m02 選 `run_sql`；只能選固定工具的 6 題（a01、a03、a04、a05、a07、m07）全對；總選對數不低於基準。

- [ ] **Step 5: 停止條件**：達到上面的條件就停。8 輪內都沒達到，就把 `jevCriteria` 還原成第三版，在紀錄寫下結論（這也算一個結果），然後跳過 Task 3 的評測，只更新 README 的說明。

- [ ] **Step 6: 把修好 m02 的關鍵字加進測試**：在 `testCriteriaPutConfusableWordsUnderRunSql` 加一條，斷言那個字在 `runSql` 裡、不在 `busy` 裡。原有的斷言全部保留。

Run: `cd backend; python -m pytest tests/qa/test_jev.py tests/evals/test_route.py -v`
Expected: 全部 PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/modules/qa/jev.py backend/tests/qa/test_jev.py docs/superpowers/specs/2026-11-23-jev-routing-design.md
git commit -m "問答 jev：第四版選項說明，計數題改選 run_sql"
```

---

### Task 3: 完整評測確認並更新 README

**Files:**
- Modify: `README.md`（「agent vs agent＋Jev」那一節的表格與結論）

**Interfaces:**
- Consumes: Task 2 的新 `jevCriteria`

- [ ] **Step 1: 取得同意**：依 README 的花費表，Haiku jev 的 dev 約 US$0.028、test 約 US$0.019，合計約 US$0.05。使用者同意後才執行。

- [ ] **Step 2: 跑 dev**

Run: `cd backend; python -m evals.run --split dev --mode jev --model anthropic/claude-haiku-5.5`
Expected: 目標是 ≥ 36/40，且 m02 ✅。Haiku 每次會有一兩題的隨機變動，所以如果出現 m02 以外的新錯題，要逐題看是選錯工具還是 SQL 變動，寫進紀錄。

- [ ] **Step 3: 跑 test，只看總分**

Run: `cd backend; python -m evals.run --split test --mode jev --model anthropic/claude-haiku-5.5`
Expected: 只印總分。跟第三版的 21/25 比較，不打開逐題結果。

- [ ] **Step 4: 更新 README**：表格新增「Haiku 5.5 jev（第四版說明）」一列（dev、誰有空、test、平均秒數、tokens）。「選項說明很重要」那一段補一句：新的選工具評測（`python -m evals.route`）的結果，以及 m02 是怎麼修好的。

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "README：Jev 第四版說明與選工具評測的結果"
```
