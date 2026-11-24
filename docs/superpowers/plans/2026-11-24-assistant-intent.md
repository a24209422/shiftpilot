# 助理當唯一入口＋Jev 意圖工具組 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `assistant-jev` 模式：Jev 判斷意圖、給模型對應的工具組，並讓它成為問答面板的預設入口；模式選單收進開發者模式。

**Architecture:** 後端新增 `qa/intent.py`（意圖、工具組、問 Jev），`jev.py` 抽出共用的呼叫函式；`service.ask` 多一個模式，依意圖篩 `assistantToolDefinitions` 並用依工具組產生的 system prompt。前端新增開發者模式 hook、依上一則回覆決定 `previousIntent`，在工具步驟顯示意圖。新增只呼叫 Jev 的 `python -m evals.intent`。

**Tech Stack:** Python 3.13、FastAPI、psycopg、httpx、pytest；React、TypeScript、TanStack Query、Vitest。

**Spec:** `docs/superpowers/specs/2026-11-24-assistant-intent-design.md`

## Global Constraints

- 縮排 2 個空白；變數與函式用 camelCase；註解用正體中文，只寫「為什麼」。
- `pipeline`、`agent`、`jev`、`assistant` 四種模式的行為不變；`assistant` 的 system prompt 一個字都不變。
- 現有 jev 模式的 `jevCriteria`、`jevOptions`、`chooseTool` 不改，`tests/qa/test_jev.py` 不改也要全過。
- 送給 Jev 的只有：精簡日期參考（`jev.buildJevDateReference`）＋這一題的問題＋選項說明。不送對話紀錄、不送資料。
- 沒設 `JEV_API_KEY` 時 `assistant-jev` 不回 503，退回 9 個工具全給，`fallbackReason = "not_configured"`。
- 意圖 id 固定為 `query`、`booking`、`manageBooking`、`leave`；`previousIntent` 另外接受 `"all"`。
- 意圖評測只跑 dev，不打開 `backend/evals/heldout_cases.py`。
- 呼叫 Jev 或雲端模型（Haiku）前，先估價並取得使用者同意。

## Review Focus

1. **辦事題被判成 `query`**：模型手上沒有提議工具，可能回答「已幫你訂好」。期待：`query` 工具組的 prompt 有「只能查資料」那條規則（Task 2 測試）。
2. **使用者取消確認卡後問新問題**：期待重新問 Jev，不沿用（取消會補一則系統紀錄，所以最後一則是 note；Task 5 測試）。
3. **`previousIntent` 是亂填的值或其他模式帶了它**：`assistant-jev` 回 422 `{field: "previousIntent"}`，其他模式忽略（Task 3 測試）。
4. **查詢失敗（422 `QA_QUERY_FAILED`）時面板仍要能顯示意圖**：錯誤 details 帶 `intent`（Task 3 測試）。
5. **關掉開發者模式後，之前在選單選過別的模式**：一律送 `assistant-jev`（Task 6 測試）。

---

### Task 1: 意圖模組與 Jev 共用呼叫

**Files:**
- Modify: `backend/app/modules/qa/jev.py`
- Create: `backend/app/modules/qa/intent.py`
- Test: `backend/tests/qa/test_intent.py`

**Interfaces:**
- Produces（`jev.py`）：
  - `parseJevResponse(payload, options: list[str] = jevOptions, name: str = questionName) -> tuple[str, float, int | None]`
  - `callJev(request: dict, options: list[str], name: str, client: httpx.Client | None = None) -> JevDecision`：從現在的 `chooseTool` 抽出（連線、遮 key、逾時、`bad_response`／`unavailable`／`low_confidence`），`chooseTool` 改成呼叫它，行為不變。
- Produces（`intent.py`）：
  - `intentNames = ["query", "booking", "manageBooking", "leave"]`、`allTools = "all"`、`questionName = "intent"`
  - `intentTools: dict[str, list[str]]`（值照下表，順序照表）
  - `intentCriteria: dict[str, str]`
  - `@dataclass IntentDecision(name: str | None, confidence: float | None, fallbackReason: str | None, reused: bool, promptTokens: int | None, seconds: float)`
  - `buildIntentRequest(question: str, now: datetime) -> dict`
  - `chooseIntent(question: str, now: datetime, client: httpx.Client | None = None) -> IntentDecision`：沒設 key 直接回 `IntentDecision(None, None, "not_configured", False, None, 0.0)`，不發 HTTP。
  - `toolsFor(name: str | None) -> list[str] | None`：`None` 或 `"all"` 回 `None`（代表全部）。

| 意圖 | 工具（順序照此） |
|---|---|
| `query` | `run_sql`、`find_available_people`、`get_busy_periods`、`find_available_resources` |
| `booking` | `run_sql`、`find_available_people`、`get_busy_periods`、`find_available_resources`、`propose_booking` |
| `manageBooking` | `run_sql`、`find_available_people`、`get_busy_periods`、`find_available_resources`、`propose_reschedule_booking`、`propose_cancel_booking` |
| `leave` | `run_sql`、`get_busy_periods`、`propose_leave`、`propose_withdraw_leave` |

`intentCriteria` 初版（之後 Task 4 用評測調整）：每個選項只正面寫做得到的事；`query` 寫「查看、統計、列出」人員、班表、會議、請假、資源；`booking` 寫「安排、預約一場新的會議」；`manageBooking` 寫「把已經排好的會議改到別的時間，或取消它」；`leave` 寫「替自己送出請假申請，或撤回還沒核准的請假申請」。

- [ ] **Step 1: Write the failing tests**（仿 `test_jev.py` 的 `jevEnv` fixture、`goodPayload`、`clientReturning`，選項換成 `intent.intentNames`、question 名稱換成 `"intent"`）

```python
def testIntentToolsAreAssistantTools():
  names = {item["function"]["name"] for item in assistant.assistantToolDefinitions}
  assert list(intent.intentTools) == intent.intentNames
  assert all(set(tools) <= names for tools in intent.intentTools.values())

def testIdToolsHaveRunSql():
  # bookingId、requestId 只有 run_sql 查得到
  assert "run_sql" in intent.intentTools["manageBooking"] and "run_sql" in intent.intentTools["leave"]

def testQueryHasNoProposalTools():
  assert not [name for name in intent.intentTools["query"] if name.startswith("propose_")]

def testQueryCriteriaHasNoActionVerbs():
  assert not [word for word in ("預約", "安排", "改期", "取消", "撤回", "申請") if word in intent.intentCriteria["query"]]

def testRequestHasOnlyQuestionDateAndOptions():
  payload = intent.buildIntentRequest("幫我約林小美開會", fixedNow)
  assert payload["state"] == f"{jev.buildJevDateReference(fixedNow)}\n\n使用者的問題：幫我約林小美開會"
  assert list(payload["questions"]["intent"]["criteria"]) == intent.intentNames

def testChoosesHighestIntent():  # booking 1.0 → IntentDecision("booking", 1.0, None, False, 439, …)
def testLowConfidenceFallsBack():  # 最高 0.4 → name None、fallbackReason "low_confidence"
def testUnknownOptionIsBadResponse():  # probabilities 含 "run_sql" → "bad_response"
def testHttpErrorIsUnavailableAndKeyMasked(caplog):  # 500 且回應含 key → "unavailable"，log 沒有 secretKey
def testNotConfiguredSkipsHttp(monkeypatch):  # 刪 JEV_API_KEY，client 的 handler 被呼叫就 fail → "not_configured"

@pytest.mark.parametrize("name, expected", [(None, None), ("all", None), ("leave", intent.intentTools["leave"])])
def testToolsFor(name, expected):
  assert intent.toolsFor(name) == expected
```

- [ ] **Step 2: Run** `cd backend; python -m pytest tests/qa/test_intent.py -q` → FAIL（`intent` 模組不存在）
- [ ] **Step 3: 在 `jev.py` 抽出 `callJev`、讓 `parseJevResponse` 收 `options`／`name`；建立 `intent.py`**
- [ ] **Step 4: Run** `python -m pytest tests/qa/test_intent.py tests/qa/test_jev.py -q` → 全 PASS
- [ ] **Step 5: Commit** `git add backend/app/modules/qa/jev.py backend/app/modules/qa/intent.py backend/tests/qa/test_intent.py` → `git commit -m "問答：意圖工具組與 Jev 共用呼叫"`

---

### Task 2: 依工具組產生助理 prompt

**Files:**
- Modify: `backend/app/modules/qa/prompt.py:142-160`
- Create: `backend/tests/qa/fixtures/assistant_prompt.txt`
- Test: `backend/tests/qa/test_qa_service.py`（加在 `testAssistantPromptWithoutEmployee` 後面）

**Interfaces:**
- Produces: `buildAssistantMessages(question, history, data, now, asker, toolNames: list[str] | None = None) -> list[dict]`；`None` 時輸出跟現在一字不差。

規則與工具的對應（只在該工具有給時才放，留下的條目依序重新編號 1、2、3…）：
- 工具使用原則 1 → `find_available_people`；2 → `get_busy_periods`；3 → `run_sql`；4～7 一律放。
- 助理規則 4 → `find_available_resources`；1、2、3、5 一律放。
- `toolNames` 裡沒有任何 `propose_` 開頭的工具時，助理規則最後加一條：`這題只能查資料；使用者其實想辦事的話，請他直接說要做什麼，不要說已經辦好。`

- [ ] **Step 1: 改程式前，先把現在的輸出存成 fixture**：用 `toolWorld` 同樣的資料、`Asker(toolWorld.bob, "bob", "工程部")`、`now`，把 `buildAssistantMessages("再來呢", [], …)[0]["content"]` 寫進 `tests/qa/fixtures/assistant_prompt.txt`（UTF-8）。
- [ ] **Step 2: Write the failing tests**

```python
def testAssistantPromptUnchanged(toolWorld):
  expected = (Path(__file__).parent / "fixtures" / "assistant_prompt.txt").read_text(encoding="utf-8")
  asker = Asker(toolWorld.bob, "bob", "工程部")
  allNames = [item["function"]["name"] for item in assistant.assistantToolDefinitions]
  assert prompt.buildAssistantMessages("再來呢", [], toolWorld.data, now, asker)[0]["content"] == expected
  assert prompt.buildAssistantMessages("再來呢", [], toolWorld.data, now, asker, allNames)[0]["content"] == expected

def testLeavePromptDropsMissingToolRules(toolWorld):
  system = prompt.buildAssistantMessages("請假", [], toolWorld.data, now, None, intent.intentTools["leave"])[0]["content"]
  assert "find_available_people" not in system and "find_available_resources" not in system
  assert "1. 問某個人或某個資源" in system and "這題只能查資料" not in system

def testQueryPromptForbidsClaimingDone(toolWorld):
  system = prompt.buildAssistantMessages("誰有空", [], toolWorld.data, now, None, intent.intentTools["query"])[0]["content"]
  assert "這題只能查資料；使用者其實想辦事的話，請他直接說要做什麼，不要說已經辦好。" in system
```

- [ ] **Step 3: Run** `python -m pytest tests/qa/test_qa_service.py -q -k Prompt` → 新的兩個 FAIL，`testAssistantPromptUnchanged` PASS
- [ ] **Step 4: 實作 `toolNames` 參數**（規則用 `(工具名或 None, 文字)` 的串列，篩完再編號）
- [ ] **Step 5: Run** `python -m pytest tests/qa -q` → 全 PASS
- [ ] **Step 6: Commit** `git commit -m "問答：助理 prompt 依工具組只列有給的工具"`

---

### Task 3: `assistant-jev` 模式（service、router、預設模式）

**Files:**
- Modify: `backend/app/modules/qa/service.py`、`backend/app/modules/qa/router.py`、`.env.example:25`、`README.md`（「助理模式」一節與第 99 行的預設模式說明）
- Test: `backend/tests/qa/test_qa_service.py`、`backend/tests/qa/test_qa_api.py`

**Interfaces:**
- Consumes: `intent.chooseIntent`、`intent.toolsFor`、`intent.intentNames`、`intent.IntentDecision`（Task 1）；`buildAssistantMessages(..., toolNames)`（Task 2）
- Produces:
  - `service.modes = ("pipeline", "agent", "jev", "assistant", "assistant-jev")`；`resolveMode(None)` 沒設 `QA_MODE` 時回 `"assistant-jev"`；錯誤訊息列出 5 個模式。
  - `service.ask(..., history=None, previousIntent: str | None = None, chooseIntent=intent.chooseIntent)`
  - `runAssistantMode(..., asker, toolNames: list[str] | None = None, decision: IntentDecision | None = None)`：`toolNames` 不是 `None` 時只給 `assistantToolDefinitions` 中名稱在裡面的定義；`decision` 不是 `None` 時回傳與 422 details 都帶 `"intent": dataclasses.asdict(decision)`。
  - `AskBody.previousIntent: str | None = None`，router 轉給 `service.ask`；router 跟現在一樣在呼叫時才取函式（`chooseIntent=intent.chooseIntent`），API 測試才能 monkeypatch。`mode` 的 `Literal` 加 `"assistant-jev"`。

行為：
- `history` 在 `assistant` 與 `assistant-jev` 都驗證、都送給模型。
- `assistant-jev` 才看 `previousIntent`：不在 `intentNames` 也不是 `"all"` → `AppError("VALIDATION", "previousIntent 不正確", 422, {"field": "previousIntent"})`，在拿名額之前擋。合法時不呼叫 Jev，`decision = IntentDecision(name 或 None（"all"）, None, None, True, None, 0.0)`。
- 沒帶 `previousIntent` 時，在關掉請求連線之後、開沙盒之前呼叫 `chooseIntent(question, now)`（跟 jev 一樣）。

- [ ] **Step 1: 改測試輔助與既有測試**：`tests/qa/test_qa_service.py` 的 `ask()` 預設 `mode="pipeline"`（原本的 pipeline 測試都靠預設）；`testDefaultModeIsPipeline` 改成 `testDefaultModeIsAssistantJev`（`service.resolveMode(None) == "assistant-jev"`）；`tests/qa/test_qa_api.py` 第 37、51、59 行的 POST body 加 `"mode": "pipeline"`。
- [ ] **Step 2: Write the failing tests**（`ask()` 加 `previousIntent=None, chooseIntent=None` 參數並轉給 `service.ask`）

```python
def decided(name="booking", reason=None):
  return IntentDecision(name, 0.9 if name else 0.3, reason, False, 300, 0.1)

def testAssistantJevUsesIntentTools(toolWorld):
  # 給 booking 組，toolSets[0] == intentTools["booking"]；body["intent"] == asdict(decided())；body["mode"] == "assistant-jev"
def testAssistantJevFallbackGivesAllTools(toolWorld):
  # decided(None, "low_confidence") → toolSets[0] 是 9 個；system prompt 等於 fixture（沒有「這題只能查資料」）
def testAssistantJevNotConfiguredStillAnswers(toolWorld):
  # decided(None, "not_configured") → 200，intent.fallbackReason == "not_configured"
def testPreviousIntentSkipsJev(toolWorld):
  # previousIntent="leave"，chooseIntent 被呼叫就 raise → toolSets[0] == intentTools["leave"]，intent.reused is True
def testPreviousIntentAllGivesAllTools(toolWorld):
  # previousIntent="all" → 9 個工具，intent == {"name": None, ..., "reused": True}
@pytest.mark.parametrize("value", ["foo", "", 1])
def testBadPreviousIntent(world, value):
  # VALIDATION、details == {"field": "previousIntent"}、service.askingUserIds == set()
def testOtherModesIgnorePreviousIntent(world):
  # mode="assistant"、previousIntent="foo" → 200
def testAssistantJevQueryFailedCarriesIntent(toolWorld):
  # 6 次失敗 → QA_QUERY_FAILED，error.details["intent"]["name"] == "query"
def testAssistantJevHistoryIsSent(toolWorld):
  # 同 testAssistantHistoryIsSentToModel，mode="assistant-jev"
```

API 測試加一個 `testAskAssistantJevEndToEnd`（仿 `testAskAssistantModeEndToEnd`，monkeypatch `qaIntent.chooseIntent`，body 帶 `previousIntent: "booking"` 時 chooseIntent 不被呼叫）。

- [ ] **Step 3: Run** `python -m pytest tests/qa/test_qa_service.py tests/qa/test_qa_api.py -q` → 新測試 FAIL
- [ ] **Step 4: 實作 service 與 router**
- [ ] **Step 5: Run** `python -m pytest tests -q` → 全 PASS
- [ ] **Step 6: 改 `.env.example`**：`# QA_MODE=assistant-jev   # pipeline、agent、jev、assistant 或 assistant-jev（預設）；API 沒指定模式時用這個`。README：預設模式改成「助理＋Jev」，說明意圖工具組、沒設 key 時 9 個工具全給、`?dev=1` 開模式選單。
- [ ] **Step 7: Commit** `git commit -m "問答：assistant-jev 模式，依意圖給工具組並設為預設"`

---

### Task 4: 意圖評測 `python -m evals.intent`

**Files:**
- Create: `backend/evals/intent_cases.py`、`backend/evals/intent.py`
- Test: `backend/tests/evals/test_intent.py`
- Modify: `README.md`（評測一節加用法）

**Interfaces:**
- Consumes: `intent.chooseIntent`、`intent.intentCriteria`、`intent.intentNames`（Task 1）；`evals.cases.cases`、`evals.fixture.fixedNow`、`evals.run.resultsDir`
- Produces:
  - `intent_cases.actionCases: list[dict]`，每題 `{"id", "question", "intent"}`
  - `intent.allCases() -> list[dict]`：dev 40 題（`intent: "query"`）＋`actionCases`
  - `intent.intentCase(case, chooseIntent=None, now=fixedNow) -> dict`：欄位 `id, question, expected, chosen, confidence, fallback, correct, promptTokens, seconds`
  - `intent.summarizeIntents(results) -> dict`：`split, jevModel, criteriaHash, total, correct, byIntent（每個意圖的 {total, correct}）, fallbacks, unavailable, wrongIds, queryAsAction（查詢題被判成辦事的題數）, promptTokens, estimatedUsd, finishedAt, results`
  - `intent.main(argv=None, chooseIntent=None)`；結果存 `resultsDir / "intent-dev-YYYYmmdd-HHMMSS.json"`

題目規則（`actionCases`）：`booking`、`manageBooking`、`leave` 各 8 題，id 用 `ib01`～`ib08`、`im01`～`im08`、`il01`～`il08`（不跟 `cases.py` 撞）；每個意圖至少 2 題直接下指令、2 題先問再辦（例如「明天下午誰有空？有的話幫我約」）、2 題口語；`manageBooking` 改期與取消各至少 3 題；`leave` 請假與撤回各至少 3 題；不照抄 `cases.py` 的句子。寫完列給使用者抽查再往下。

- [ ] **Step 1: Write the failing tests**（仿 `tests/evals/test_route.py`，Jev 用假的 `chooseIntent`）

```python
def testAllCasesLabelDevAsQuery():
  # allCases() 前 40 題 id 等於 cases.py 的 id 且 intent 全是 "query"
def testActionCaseCounts():
  # 三個辦事意圖各 8 題、id 不重複、不跟 cases.py 重複
def testIntentCaseCorrectAndWrong():
def testFallbackIsNotCorrect():
def testSummaryCountsQueryAsAction():
  # 一題 expected query、chosen booking → queryAsAction == 1
def testUnavailableCountedSeparately():
def testMainWithoutKeyExits(monkeypatch, capsys):
def testMainRunsEveryCaseAndSaves(monkeypatch, tmp_path):
```

- [ ] **Step 2: Run** `python -m pytest tests/evals/test_intent.py -q` → FAIL
- [ ] **Step 3: 寫 `intent_cases.py`，請使用者抽查題目**
- [ ] **Step 4: 實作 `evals/intent.py`**（印每題 ✅／❌／↩️、總結一行含 `queryAsAction`、Jev tokens、估計花費、說明版本）
- [ ] **Step 5: Run** `python -m pytest tests/evals -q` → 全 PASS
- [ ] **Step 6: 估價後經使用者同意，跑一次** `python -m evals.intent`；依結果只看 dev 調 `intentCriteria`，每調一版重跑。把最後結果寫進 README（選對數、`queryAsAction`、花費）。
- [ ] **Step 7: Commit** `git commit -m "評測：只呼叫 Jev 的意圖評測"`

---

### Task 5: 前端型別、沿用意圖、顯示意圖

**Files:**
- Modify: `frontend/src/api/types.ts:86-100`、`frontend/src/shell/QaMessage.tsx`
- Test: `frontend/src/shell/sidePanel.test.tsx`

**Interfaces:**
- Produces:
  - `type QaMode = "pipeline" | "agent" | "jev" | "assistant" | "assistant-jev"`
  - `type QaIntentName = "query" | "booking" | "manageBooking" | "leave"`
  - `interface QaIntent { name: QaIntentName | null; confidence: number | null; fallbackReason: string | null; reused: boolean; promptTokens: number | null; seconds: number }`；`QaAnswer.intent?: QaIntent`
  - `QaMessage.tsx` export `previousIntentFor(entries: ChatEntry[]): QaIntentName | "all" | null`：最後一則是 `answer` 且有 `intent`，並且（有 `proposal`，或 `rows` 為空且沒有 `proposal`）→ `intent.name ?? "all"`；其他（沒有、最後一則是 note／error／question、上一則是有資料的表格）→ `null`。
  - `intentText(intent: QaIntent): string`（同檔，不 export 也可）

顯示文字（照抄）：意圖中文名 `query` 查詢、`booking` 預約會議、`manageBooking` 改期或取消會議、`leave` 請假或撤回請假。
- 有 name、沒沿用：`Jev 判斷：預約會議（信心 0.92）`
- 沿用、有 name：`沿用上一輪的意圖：預約會議`
- 沿用、沒 name：`沿用上一輪：9 個工具都給`
- `not_configured`：`沒設定 Jev，9 個工具都給`
- 其他退回：`Jev 沒選定（信心不足），9 個工具都給`（原因文字沿用 `fallbackText`）

`StepList` 的顯示條件改成 steps 非空、或有 `route`、或有 `intent`。

- [ ] **Step 1: Write the failing tests**

```ts
test("testPreviousIntentAfterClarifyingReply", () => {
  // [question, answer(rows: [], proposal: null, intent booking)] → "booking"
});
test("testPreviousIntentAfterOpenProposal", () => { /* proposal 不是 null → intent.name */ });
test("testNoPreviousIntentAfterNote", () => { /* 最後一則是 note（確認或取消後）→ null */ });
test("testNoPreviousIntentAfterTable", () => { /* rows 有資料 → null */ });
test("testPreviousIntentAllWhenFallback", () => { /* intent.name null、reused false → "all" */ });
test("testIntentIsShown", async () => { /* 回覆帶 intent booking 0.923 → 展開「看工具步驟」看到「Jev 判斷：預約會議（信心 0.92）」 */ });
test("testIntentNotConfiguredIsShown", async () => { /* 「沒設定 Jev，9 個工具都給」 */ });
test("testReusedIntentIsShown", async () => { /* 「沿用上一輪的意圖：預約會議」 */ });
```

- [ ] **Step 2: Run** `cd frontend; npx vitest run src/shell/sidePanel.test.tsx` → 新測試 FAIL
- [ ] **Step 3: 實作型別、`previousIntentFor`、`intentText` 與 `StepList` 條件**
- [ ] **Step 4: Run** `npx vitest run` → 全 PASS
- [ ] **Step 5: Commit** `git commit -m "問答面板：顯示 Jev 意圖並算出要沿用的意圖"`

---

### Task 6: 開發者模式與預設入口

**Files:**
- Create: `frontend/src/shell/devMode.ts`
- Modify: `frontend/src/shell/SidePanel.tsx:31,66-69,168-173`
- Test: `frontend/src/shell/sidePanel.test.tsx`

**Interfaces:**
- Consumes: `previousIntentFor`（Task 5）
- Produces: `useDevMode(): boolean`：用 react-router 的 `useLocation().search` 讀 `dev`；`"1"` 時寫 `localStorage["shiftpilot.dev"] = "1"` 並回 true，`"0"` 時刪掉並回 false，沒帶時看 `localStorage`。

SidePanel 行為：
- `mode` 初始值 `"assistant-jev"`；實際送出的模式 `sentMode = devMode ? mode : "assistant-jev"`。
- 模式選單只在 `devMode` 時畫出，選項多一個 `<option value="assistant-jev">助理＋Jev</option>`。
- `sentMode` 是 `assistant` 或 `assistant-jev` 時送 `history`；是 `assistant-jev` 且 `previousIntentFor(entries)` 不是 null 時送 `previousIntent`。

- [ ] **Step 1: 改既有測試**：`afterEach` 加 `localStorage.clear()`；`open()` 加 `route` 參數，用到「模式」選單的測試改用 `open(routes, perms, "/?dev=1")`；`testAskShowsAnswerTableAndSql` 等原本預期 `mode: "pipeline"` 的 body 改成 `{ question, model, mode: "assistant-jev", history: [] }`。
- [ ] **Step 2: Write the failing tests**

```ts
test("testModeSelectHiddenByDefault", async () => { /* open() → queryByRole("combobox", { name: "模式" }) 是 null */ });
test("testDevModeShowsAllModes", async () => { /* "/?dev=1" → 5 個 option，預設值 assistant-jev */ });
test("testDevModeIsRemembered", async () => { /* 先 "/?dev=1" unmount，再 "/" → 選單還在 */ });
test("testDevModeOff", async () => { /* localStorage 有值、"/?dev=0" → 沒有選單 */ });
test("testSendsPreviousIntentAfterClarifying", async () => {
  // 第一題回 { ...answer, rows: [], mode: "assistant-jev", intent: booking }，第二題的 body.previousIntent === "booking"
});
test("testNoPreviousIntentOnFirstQuestion", async () => { /* body 沒有 previousIntent */ });
test("testDevModeOffAlwaysSendsAssistantJev", async () => { /* localStorage 無值 → body.mode === "assistant-jev" */ });
```

- [ ] **Step 3: Run** `npx vitest run src/shell/sidePanel.test.tsx` → 新測試 FAIL
- [ ] **Step 4: 實作 `useDevMode` 與 SidePanel 修改**
- [ ] **Step 5: Run** `npx vitest run`，以及 `npx tsc --noEmit`（或專案的 build 指令）→ 全過
- [ ] **Step 6: Commit** `git commit -m "問答面板：預設助理＋Jev，模式選單收進開發者模式"`

---

### Task 7: 端到端驗收

**Files:** 無（只驗證；發現問題回到對應的 Task 修）

- [ ] **Step 1:** `cd backend; python -m pytest tests -q`、`cd frontend; npx vitest run` → 全過
- [ ] **Step 2:** 用 `.claude/launch.json` 的 `backend-host-8001` 開 `127.0.0.1:8001`（記得先 build 前端）。不帶 `?dev`：沒有模式選單；`?dev=1`：5 個選項；`?dev=0`：又不見。
- [ ] **Step 3（要花錢，先估價取得同意）:** Haiku 5.5、有 `JEV_API_KEY`，照 spec「驗收」第 2 點跑 5 個情境，確認意圖、確認卡、「沿用上一輪的意圖」都對。
- [ ] **Step 4:** 拿掉 `JEV_API_KEY` 重開，問一題，看到「沒設定 Jev，9 個工具都給」且有回答。
- [ ] **Step 5:** 截圖給使用者，回報結果。
