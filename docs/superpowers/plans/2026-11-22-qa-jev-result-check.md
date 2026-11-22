# 問答 check 模式（Jev 檢查工具結果）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增第四種問答模式 `check`：agent 迴圈三個工具都給，每次工具成功後問 Jev 一題是非題「這份結果有回答問題嗎？」，判斷「沒有」就餵固定提示請 LLM 重查。

**Architecture:** `jev.py` 新增 `checkResult`（永不丟例外，回傳 `CheckDecision`）。`agent.runAgent` 多一個選用的 `checker` 參數，每次成功的工具呼叫後呼叫它，拒絕時在該輪工具結果之後加一則固定提示，並把檢查記進 step 與 `outcome.checks`。`service.ask` 在 `check` 模式組出 checker 交給 agent。評測、面板多記、多顯示 `checks`。

**Tech Stack:** FastAPI、psycopg 3、httpx、pytest；React + TypeScript、vitest。

**Spec:** `docs/superpowers/specs/2026-11-22-qa-jev-result-check-design.md`

## Global Constraints

- 縮排 2 個空白、camelCase、註解用正體中文且只寫「為什麼」
- key 只放 `.env`（沿用 `JEV_API_KEY`）；錯誤訊息與 log 裡的 key 要遮成 `***`，**先遮再截斷**
- 給 Jev 的內容只能有：問題文字、`buildJevDateReference(now)`、用過的工具名稱、欄位名稱、筆數。**不能有任何資料列、SQL、資料表說明**
- 拒絕門檻：`p(是) < 0.3` 才拒絕；環境變數 `JEV_CHECK_MIN_YES` 可覆寫，無效值（非數字、nan、不在 0～1）一律用 0.3
- 每題最多拒絕 **2 次**，第 3 次起一律接受；工具呼叫上限仍是 4 次；**最後一次呼叫（用完次數）不檢查**
- Jev 任何失敗（逾時、HTTP 錯誤、格式不對）都當作「不攔」，不重試、不丟例外
- 被拒絕時餵給 LLM 的固定提示：`這份結果的欄位是：{欄位用「、」連接}。它看起來沒有回答問題，請換一個工具或改寫查詢再試。`（作為 user 訊息，放在該輪所有 tool 結果之後）
- 計分函式不變；test 只看總分，**不打開 `backend/evals/heldout_cases.py`**；門檻與說明只能看 dev 調整，調整一次並記錄
- 沒先估價、沒經使用者同意，不呼叫雲端（含 Jev）
- 在 `main` 上有未 commit 的變動（縮短日期表的 `jev.py`／`test_jev.py`、README 的 Flash-Lite 列、這份 spec 與 plan）：開工前先問使用者要不要先 commit，再從 `main` 切 `feature/qa-check`

## Review Focus

1. **一輪回多個工具呼叫，其中一個被拒絕**：提示要放在該輪所有 tool 訊息之後，訊息順序不能變成 tool 之間夾 user（Task 2 測）
2. **checker 本身丟出非預期例外**：問答不能因此失敗，照原流程接受結果（Task 2 測）
3. **0 筆結果、沒有欄位的結果**：請求照常組出、不崩潰（Task 1 測）
4. **`JEV_CHECK_MIN_YES=nan`、`-1`、`2`、空字串**：回到 0.3，不能讓門檻失效（Task 1 測）。`JEV_MIN_CONFIDENCE=nan` 有同樣的問題，但那是 jev 模式的既有行為，這份 plan 不動它
5. **用完次數與拒絕上限**：第 4 次工具呼叫不檢查；連續被拒絕只算 2 次，第 3 次起接受；被拒絕後 LLM 直接用文字收尾時，表格仍是最後一次成功的結果（Task 2 測）

---

### Task 0: 實際呼叫 Jev 的是非題（用完就丟）

**Files:**
- Modify: `docs/superpowers/specs/2026-11-22-qa-jev-result-check-design.md`（新增「Jev 是非題呼叫格式」小節）
- 腳本放暫存資料夾，不進專案

**Interfaces:**
- Produces: 回應裡「是」的機率的確切路徑、`usage.input_tokens` 路徑、`confidence` 欄位的意思；Task 1 的 `parseCheckResponse` 照這個寫

- [ ] **Step 1: 估價並問使用者**。3 次呼叫、每次約 700 輸入 tokens、約 $0.0001；得到明確同意才呼叫
- [ ] **Step 2: 寫用完即丟的腳本**，沿用 `jev.buildJevRequest` 的 `state` 組法，`questions` 換成 `{"enough": {"type": "noul", "instructions": "查到的資料欄位足以回答這個問題嗎？", "criteria": {"true": "欄位包含問題要問的內容（人、時間、假別、數量等）", "false": "少了問題要問的內容，或完全不相關"}}}`，打 `https://api.typesafe.ai/v1/systemone`（key 只送到這裡，不印出）。3 題：①「林小美這週請了什麼假？」＋工具 `get_busy_periods`＋欄位 `誰, 開始, 結束, 種類, 標題`（預期「否」）②「各種假別已核准的總時數各是多少？」＋`run_sql`＋欄位 `假別, 總時數`（預期「是」）③「這週有誰請假？」＋`get_busy_periods`＋同①欄位（預期「是」）
- [ ] **Step 3: 把回應原文與觀察寫回 spec**：機率欄位路徑、`usage` 路徑、3 題的 p 值。若格式與 Task 1 的假設不同，在這裡裁定並記進 ledger
- [ ] **Step 4: 若 3 題的 p 值明顯不能分辨「欄位夠／不夠」**（①與②③的差距小於 0.3），停下來告訴使用者，不繼續 Task 1
- [ ] **Step 5: Commit** spec 的修改

---

### Task 1: `jev.py` —— `checkResult`

**Files:**
- Modify: `backend/app/modules/qa/jev.py`
- Test: `backend/tests/qa/test_jev.py`

**Interfaces:**
- Consumes: `getJevConfig()`、`buildJevDateReference(now)`、既有的 HTTP 呼叫與錯誤遮罩流程
- Produces:
  - `@dataclass CheckDecision`：`probabilityYes: float | None`、`rejected: bool`、`fallbackReason: str | None`（`"unavailable"`、`"bad_response"` 或 `None`）、`promptTokens: int | None`、`seconds: float`
  - `buildCheckRequest(question: str, toolName: str, columns: list[str], rowCount: int, now: datetime) -> dict`
  - `parseCheckResponse(payload) -> tuple[float, int | None]`（機率、輸入 tokens；路徑依 Task 0）
  - `checkResult(question: str, toolName: str, columns: list[str], rowCount: int, now: datetime, client: httpx.Client | None = None) -> CheckDecision`
  - `getJevConfig()` 多一個 `"checkMinYes": float`

- [ ] **Step 1: 寫失敗的測試**（沿用檔內 `clientReturning`、`jevEnv`、`fixedNow`；回應以 Task 0 確認的格式組成）：
  - `testCheckRequestHasOnlyColumnsAndCount`：`state` 含問題、工具名、欄位名、筆數，不含 `prompt.schemaText`；`questions["enough"]["type"] == "noul"`，`criteria` 有 `"true"`、`"false"`；傳入含「陳大文」的欄位以外不得出現任何列內容（用欄位 `["誰"]`、列數 3，斷言 `"陳大文"` 不在請求裡）
  - `testCheckRequestWithNoRowsOrColumns`：`columns=[]`、`rowCount=0` 仍組得出請求
  - `testCheckYesAboveThresholdNotRejected`、`testCheckNoBelowThresholdRejected`（p=0.1 → `rejected=True`）、`testCheckExactlyAtThresholdNotRejected`（p=0.3）
  - `testCheckThresholdFromEnv`（`JEV_CHECK_MIN_YES=0.6`，p=0.5 → 拒絕）
  - `testCheckThresholdInvalidFallsBackToDefault`：參數化 `"nan"`、`"-1"`、`"2"`、`""`、`"abc"` → 門檻都是 0.3
  - `testCheckFailureNeverRejects`：參數化 401、429、500、逾時、非 JSON、機率 `"0.9"`（字串）、機率 1.5、缺欄位 → `rejected is False` 且 `fallbackReason` 為 `"unavailable"`／`"bad_response"`，且 `calls` 只有 1 次（不重試）
  - `testCheckMasksKeyBeforeTruncating`：key 跨過第 200 字元時 log 裡沒有半截 key
- [ ] **Step 2: 跑測試確認失敗**：`cd backend && python -m pytest tests/qa/test_jev.py -q`，Expected: 新測試 FAIL（`AttributeError`），既有 24 題仍 PASS
- [ ] **Step 3: 實作上列四個函式與 `CheckDecision`**。把 `chooseTool` 裡「POST、`raise_for_status`、錯誤遮罩與記 log」抽成共用的私有函式，兩邊都用；既有的 `chooseTool` 行為與測試不變。門檻驗證用 `math.isfinite` 且 `0 <= value <= 1`
- [ ] **Step 4: 跑測試確認全過**：`python -m pytest tests/qa/test_jev.py -q`，Expected: 全部 PASS（既有 24 ＋新增）
- [ ] **Step 5: Commit**

---

### Task 2: `agent.py` —— 迴圈支援 checker

**Files:**
- Modify: `backend/app/modules/qa/agent.py`
- Test: `backend/tests/qa/test_qa_agent.py`

**Interfaces:**
- Consumes: `jev.CheckDecision`；測試用假的 checker：`checker(toolName: str, result: ToolResult) -> CheckDecision`
- Produces:
  - `runAgent(conn, toolLlm, model, messages, allowedTools=None, checker=None) -> AgentOutcome`
  - `AgentOutcome` 多 `checks: list[dict]`、`rejections: int`
  - 每次檢查記一筆：`{"step": 第幾次工具呼叫（從 1）, "tool": 工具名, "probabilityYes": float | None, "rejected": bool, "fallbackReason": str | None, "promptTokens": int | None, "seconds": float}`，同一筆也放進對應的 `outcome.steps[i]["check"]`
  - 常數 `maxRejections = 2`、提示產生函式 `rejectionHint(columns: list[str]) -> str`

- [ ] **Step 1: 寫失敗的測試**（沿用檔內的假 `toolLlm` 與 `sandbox` fixture）：
  - `testCheckerNotCalledWhenAbsent`：不傳 checker，行為與既有測試相同（`outcome.checks == []`）
  - `testCheckRejectsThenRetries`：第一次工具結果被拒絕 → 下一輪送給 LLM 的 `messages` 最後一則是 role `user`、內容等於 `rejectionHint(欄位)`；第二次接受 → `outcome.rejections == 1`、`outcome.checks` 長度 2、`steps[0]["check"]["rejected"] is True`
  - `testHintComesAfterAllToolMessagesOfTheTurn`（Review Focus 1）：一輪兩個工具呼叫、第一個被拒絕 → 送出的 `messages` 中，兩則 `tool` 訊息之間沒有 `user`，`user` 提示在兩者之後
  - `testRejectionsCappedAtTwo`（Review Focus 5）：checker 永遠拒絕 → 只拒絕 2 次，第 3 次工具結果起接受，`outcome.rejections == 2`
  - `testLastCallNotChecked`（Review Focus 5）：`maxToolCalls` 用完的那次不呼叫 checker
  - `testFailedToolNotChecked`：工具回錯誤時不呼叫 checker
  - `testCheckerExceptionTreatedAsAccepted`（Review Focus 2）：checker 丟 `RuntimeError` → 照原流程接受，不丟出，`checks` 不新增該筆
  - `testRejectedResultStillTheTableWhenModelStopsTalking`（Review Focus 5）：被拒絕後 LLM 不再呼叫工具、直接回文字 → `outcome.result` 是被拒絕的那份結果
  - `testHintMentionsColumnsAndEmptyColumnsDoNotCrash`：`rejectionHint([])` 不崩潰
- [ ] **Step 2: 跑測試確認失敗**：`python -m pytest tests/qa/test_qa_agent.py -q`，Expected: 新測試 FAIL，既有 PASS
- [ ] **Step 3: 實作**。在 `result.ok` 之後、且 `outcome.toolCalls < maxToolCalls`、`outcome.rejections < maxRejections` 時才呼叫 checker；checker 的例外用 `logging.warning` 記下並當作接受；提示在該輪 `for toolCall` 迴圈結束後才 append，內容用最後一個被拒絕結果的欄位
- [ ] **Step 4: 跑測試確認全過**：`python -m pytest tests/qa/test_qa_agent.py -q`，Expected: 全部 PASS
- [ ] **Step 5: Commit**

---

### Task 3: service 與 API 加 `check` 模式

**Files:**
- Modify: `backend/app/modules/qa/service.py`、`backend/app/modules/qa/router.py`
- Test: `backend/tests/qa/test_qa_service.py`、`backend/tests/qa/test_qa_api.py`

**Interfaces:**
- Consumes: `jev.checkResult`、`agent.runAgent(..., checker=)`
- Produces:
  - `modes = ("pipeline", "agent", "jev", "check")`
  - `ask(..., checkResult=jev.checkResult)`（新增關鍵字參數，位置在 `jevConfigured` 之後）
  - 回應與 `QA_QUERY_FAILED` 的 details 在 `check` 模式多 `checks`（`list[dict]`，格式同 Task 2）與 `rejections`
  - API `mode` 接受 `"check"`

- [ ] **Step 1: 寫失敗的測試**：
  - `testCheckModeUsesChecker`：`mode="check"` 時 agent 迴圈拿到三個工具（不受限）、checker 被呼叫，回應有 `checks` 且 `mode == "check"`
  - `testCheckModeBindsQuestionAndColumns`：假 `checkResult` 收到的 `question`、工具名、欄位、筆數正確
  - `testCheckModeWithoutKeyIs503BeforeSlot`：沒設 key → `QA_NOT_CONFIGURED`，訊息含 `check 模式還沒設定`，且沒有佔用名額、沒讀沙盒資料
  - `testAgentAndJevModesUnchanged`：既有 agent／jev 測試不改、全過
  - `testResolveModeAcceptsCheck`（含 `QA_MODE=check`）、`testResolveModeErrorMentionsAllModes`
  - API：`testApiAcceptsCheckMode`、`testApiRejectsUnknownMode`
- [ ] **Step 2: 跑測試確認失敗**：`python -m pytest tests/qa/test_qa_service.py tests/qa/test_qa_api.py -q`
- [ ] **Step 3: 實作**：`ask` 在 `check` 模式用 `functools.partial` 或 lambda 把 `question`、`now` 綁進 checker，交給 `runAgentMode`；沒設 key 的擋法沿用 jev 的位置與寫法，訊息改成用模式名稱；`router.py` 的 `Literal` 加 `"check"`，並在呼叫 `ask` 時才取 `jev.checkResult`（測試才換得掉）
- [ ] **Step 4: 跑測試確認全過**：`python -m pytest tests/qa -q`，Expected: 全部 PASS
- [ ] **Step 5: Commit**

---

### Task 4: 評測 `--mode check` 與逐題比對

**Files:**
- Modify: `backend/evals/run.py`
- Create: `backend/evals/compare.py`
- Test: `backend/tests/evals/test_run.py`、`backend/tests/evals/test_compare.py`

**Interfaces:**
- Consumes: Task 3 回應裡的 `checks`、`rejections`
- Produces:
  - `run.agentModes = ("agent", "jev", "check")`；`--mode` 接受 `check`
  - 每題結果多：`checkCount`、`rejections`、`checks`（原樣）、`jevPromptTokens`（check 模式是各次檢查的加總）、`jevSeconds`（加總）
  - summary 多（只在 `check` 模式）：`checkTotal`、`rejectionTotal`、`casesWithRejection`、`jevPromptTokens`
  - `compare.py`：`python -m evals.compare <基準結果.json> <比較結果.json>`；`compareResults(base: dict, other: dict) -> dict`（`{"fixed": [題號], "broken": [題號], "stillWrong": [...], "scoreDiff": int}`）
  - hidden split（test）：逐題的 `checks`、`checkCount`、`rejections` 與 `compare` 的逐題輸出都不得出現；aggregate 的四個數字可以

- [ ] **Step 1: 寫失敗的測試**：
  - `run`：`testCheckModeRecordsChecks`（假 checker 拒絕 1 次 → 每題結果 `rejections == 1`、`checkCount == 2`）、`testCheckSummaryAggregates`、`testHiddenSplitHidesPerCaseChecks`（沿用 `testHiddenSplitWithFailuresLeaksNothing` 的做法，`allowedTestKeys` 加 `checkTotal`、`rejectionTotal`、`casesWithRejection`）、`testCheckModeWithoutKeyAbortsBeforeScoring`、`testPrintCaseShowsRejection`（終端輸出「Jev 判斷沒答到題，重查」）
  - `compare`：`testFixedAndBroken`、`testRefusesTestSplit`（任一檔 `split == "test"` → 只印總分差、不列題號）、`testRefusesDifferentSplits`
- [ ] **Step 2: 跑測試確認失敗**：`python -m pytest tests/evals -q`
- [ ] **Step 3: 實作** `run.py` 的 `evaluateCase`／`summarize`／`printCase`／`--mode`；新增 `compare.py`（讀兩個結果檔、依題號比對 `outcome`）
- [ ] **Step 4: 跑測試確認全過**：`python -m pytest tests/evals -q`，Expected: 全部 PASS
- [ ] **Step 5: Commit**

---

### Task 5: 問答面板

**Files:**
- Modify: `frontend/src/api/types.ts`、`frontend/src/shell/SidePanel.tsx`、`frontend/src/shell/QaMessage.tsx`
- Test: `frontend/src/shell/sidePanel.test.tsx`

**Interfaces:**
- Consumes: Task 3 的回應欄位（`checks`、每個 step 的 `check`）
- Produces: `QaMode` 多 `"check"`；新 `QaCheck` 型別（欄位同 Task 2）；`QaStep.check?: QaCheck`；`QaAnswer.checks?: QaCheck[]`

- [ ] **Step 1: 寫失敗的測試**：模式選單有「Agent＋檢查」且值為 `check`；送出時 `mode` 為 `check`；回應的 step 有 `check.rejected === true` 時，步驟旁顯示「Jev 判斷沒答到題，重查」；沒有被拒絕時不顯示；沒有 `checks` 的 agent／jev 回應畫面不變
- [ ] **Step 2: 跑測試確認失敗**：`cd frontend && npx vitest run src/shell/sidePanel.test.tsx`
- [ ] **Step 3: 實作**，樣式沿用現有 `qaRoute` 那一行的風格
- [ ] **Step 4: 跑測試確認全過**：`npx vitest run`，Expected: 全部 PASS
- [ ] **Step 5: Commit**

---

### Task 6: 跑評測、寫對照、判斷採用與否

**Files:**
- Modify: `README.md`（在「agent vs agent＋Jev」之後新增「agent vs agent＋檢查」小節）、`.env.example`（`QA_MODE` 註解加 `check`；`JEV_CHECK_MIN_YES` 註解行）
- Modify: spec 的「Jev 是非題呼叫格式」若 Task 0 後有變

**Interfaces:**
- Consumes: Task 0～5 全部

- [ ] **Step 1: 全部測試**：`cd backend && python -m pytest -q`（約 17 分鐘，背景跑、輸出導到檔案讀結尾）、`cd frontend && npx vitest run`，Expected: 全 PASS
- [ ] **Step 2: 估價並問使用者**：3b 的 `--filter avail` 7 題（只有 Jev 要錢，約 $0.0003）；同意後執行 `python -m evals.run --split dev --mode check --filter avail`（`.env` 的 `OLLAMA_MODEL`）。Expected: 沒有連線錯誤、`checks` 有記錄、分數不低於 agent 模式
- [ ] **Step 3: 估價並問使用者**：Haiku（`anthropic/claude-haiku-5.5`）完整 dev，Jev 約 $0.0014＋LLM 約 $0.03～$0.04；同意後執行 `--split dev --mode check --model anthropic/claude-haiku-5.5`
- [ ] **Step 4: 用 `python -m evals.compare` 跟 Haiku agent 的 dev 結果（`dev-agent-anthropic_claude-haiku-5.5-20261122-170907.json`）逐題比對**，依 spec 的成功標準判斷：≥ 35/40 且「對→錯」≤ 1 題採用；34～35 或救回與誤擋相當寫「沒有明顯好處」；< 33/40 或誤擋 ≥ 3 題不採用。若需要調整 Noul 說明、提示措辭或門檻，**只能調整一次**、只看 dev、並記錄調整前後
- [ ] **Step 5: test 另外問使用者**（估價 Haiku 約 $0.03＋Jev 約 $0.0008）；只看總分
- [ ] **Step 6: 寫 README 小節**：對照表（分數、秒數、平均工具呼叫、被檢查次數、被拒絕次數、Jev tokens）、救回與誤擋的題號與原因（只用 dev）、花費（Haiku 用 OpenRouter 價格、Jev $0.042／百萬輸入 tokens）、結論（包含「沒有效果」的可能）。更新「Jev 價格未經官方確認」的說法：OpenRouter 頁面已列出同樣的 $0.042／百萬輸入、輸出 $0
- [ ] **Step 7: Commit**，再依 superpowers:finishing-a-development-branch 處理分支（合併前先問使用者）
