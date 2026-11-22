# 排程助理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 問答面板加上「助理」模式：多輪對話、能查能總結，並能提議預約／請假動作，使用者在確認卡按下確認後，由前端呼叫現有 API 寫入。

**Architecture:** 後端新增 `assistant` 模式，沿用 `runAgent` 迴圈（加上可指定工具、執行器、上限），多一個查詢工具和 5 個「提議工具」。提議工具只產生結構化的 `proposal`，不寫資料。前端把 `proposal` 畫成確認卡，確認後用現有的 `apiSend` 呼叫既有的寫入 API。

**Tech Stack:** FastAPI、psycopg、PostgreSQL（後端）；React、TypeScript、TanStack Query、Vitest（前端）

**Spec:** `docs/superpowers/specs/2026-11-22-assistant-design.md`

## Global Constraints

- 縮排 2 個空白；變數與函式用 camelCase；註解用正體中文，只寫「為什麼」
- `pipeline`、`agent`、`jev` 三種模式的行為不能變：`tools.toolDefinitions`、`tools.handlers`、`sandboxTables`、`schemaText`、`buildAgentMessages` 都不能改
- 助理專用的工具不加進 `tools.toolDefinitions`
- 提議工具不寫任何資料，也不接觸寫入用的連線
- history 上限：後端最多 40 則、每則最多 1000 字，role 只能是 `user` 或 `assistant`
- 動作結果在 history 裡以 `（系統紀錄）` 開頭、`role: "user"`
- 助理模式的工具上限是 6 次，其他模式維持 4 次（`agent.maxToolCalls = 4` 不變）
- 會議 `category` 固定是 `會議`；不帶 `organizerEmployeeId`
- 寫入 API 的時間格式是 `YYYY-MM-DDTHH:MM`；工具參數的時間格式是 `YYYY-MM-DD HH:MM`
- 呼叫雲端模型（Haiku 5.5）前要先估價、等使用者同意；不得開啟 `backend/evals/heldout_cases.py`、`backend/evals/ext_heldout_cases.py`
- 後端測試：`cd backend; python -m pytest tests/qa -q`（要先 `docker compose up -d --wait postgres`）；前端：`cd frontend; npm test`

## Review Focus

1. 名稱只講一部分、對到多個人或資源（「bo」同時對到 bob、boss）時，要回工具錯誤並列出候選，不能任意挑一個 → Task 3 `testAmbiguousNameListsCandidates`
2. 同一輪裡模型呼叫兩個提議工具：只採用第一個，第二個不執行 → Task 2 `testOnlyFirstProposalIsKept`
3. 舊的確認卡還沒處理，又出現新的提議：舊卡要失效、不能按 → Task 7 `testOlderProposalIsSuperseded`
4. 確認時資料已經變了（例如會議已被取消，API 回 404 或 409）：卡片顯示錯誤訊息，不能當成成功 → Task 7 `testConfirmErrorIsShown`
5. 開始時間等於或晚於結束時間：提議工具要擋下，因為 `parseRange` 允許兩者相等 → Task 3 `testProposalRejectsEmptyRange`

---

## 檔案結構

| 檔案 | 責任 |
|---|---|
| `backend/app/modules/qa/sandbox.py`（改） | `SandboxData` 多一個 `leaveTypes` 欄位（id、名稱），不進沙盒資料表 |
| `backend/app/modules/qa/tools.py`（改） | `ToolResult` 多一個預設為 `None` 的 `proposal` 欄位 |
| `backend/app/modules/qa/agent.py`（改） | `runAgent` 可以指定工具定義、執行器、上限；遇到提議就停 |
| `backend/app/modules/qa/proposals.py`（新） | 提問者資訊、名稱轉 id、5 個提議工具、確認卡摘要格式 |
| `backend/app/modules/qa/assistant.py`（新） | 助理的工具定義、`find_available_resources`、執行器 |
| `backend/app/modules/qa/prompt.py`（改） | 新增 `buildAssistantMessages` |
| `backend/app/modules/qa/service.py`、`router.py`（改） | `assistant` 模式、history 驗證 |
| `frontend/src/api/types.ts`（改） | `QaMode` 加 `assistant`、`QaProposal`、`QaHistoryItem` |
| `frontend/src/shell/SidePanel.tsx`、`QaMessage.tsx`（改） | 模式選項、送 history、系統紀錄、清除對話 |
| `frontend/src/shell/ProposalCard.tsx`（新） | 確認卡 |
| `frontend/src/modules/leave/MeetingWarning.tsx`（新，從 `LeaveRequestForm.tsx` 搬出） | 請假的會議衝突提示，給表單和確認卡共用 |

---

### Task 1: 沙盒資料帶假別 id

**Files:**
- Modify: `backend/app/modules/qa/sandbox.py`（`SandboxData`、`collectSandboxData`）
- Test: `backend/tests/qa/test_sandbox_data.py`

**Interfaces:**
- Produces: `SandboxData.leaveTypes: list[tuple[int, str]]`，內容是啟用中的假別 `(id, name)`，依 id 排序。這個欄位要放在 dataclass 的最後並給預設值 `field(default_factory=list)`，現有直接建 `SandboxData(...)` 的測試才不用改。

- [ ] **Step 1: 寫失敗的測試** `testLeaveTypesCarryIds`：用 `makeWorld` 建資料，`collectSandboxData(conn, w.bobActor, date(2026, 11, 21))`，斷言 `{name for _, name in data.leaveTypes} == set(data.vocabulary["leaveTypes"])`，且每個 id 都在 `w.types.values()` 裡。另外斷言 `"leaveTypes" not in data.rows`，確保沒有進沙盒資料表。
- [ ] **Step 2: 執行，確認失敗**：`python -m pytest tests/qa/test_sandbox_data.py -q`，應該出現 `AttributeError: 'SandboxData' object has no attribute 'leaveTypes'`
- [ ] **Step 3: 實作**：在 `collectSandboxData` 用 `tuples(conn, "SELECT id, name FROM leave_types WHERE is_active ORDER BY id")` 填入。
- [ ] **Step 4: 執行 `python -m pytest tests/qa -q`**，全部通過（現有的 pipeline／agent 測試不受影響）
- [ ] **Step 5: Commit**：`git commit -m "問答助理：沙盒資料帶假別 id"`

### Task 2: `runAgent` 可指定工具與上限，遇到提議就停

**Files:**
- Modify: `backend/app/modules/qa/tools.py`（`ToolResult`）、`backend/app/modules/qa/agent.py`
- Test: `backend/tests/qa/test_qa_agent.py`

**Interfaces:**
- Produces:
  - `ToolResult` 多一個欄位 `proposal: dict | None = None`，放在最後。
  - `runAgent(conn, toolLlm, model, messages, allowedTools=None, *, definitions: list[dict] | None = None, execute=None, maxCalls: int = maxToolCalls) -> AgentOutcome`
    - `definitions` 是 `None` 時用 `tools.toolDefinitions`。
    - `execute(conn, name, arguments) -> ToolResult` 是 `None` 時用 `tools.executeTool`。
  - `AgentOutcome` 多一個欄位 `proposal: dict | None = None`。
- 規則：
  - 某個工具結果帶 `proposal` 時，記到 `outcome.proposal`，同一輪後面的 tool call 都不執行、不記入 `steps`，並且立刻結束迴圈，不再呼叫模型。
  - `outcome.answer` 取這一輪模型的文字（先經過 `stripThink`），是空字串時用 `請確認以下內容。`。
  - 帶 `proposal` 的結果不算 `outcome.result`，表格維持上一個查詢結果。

- [ ] **Step 1: 寫失敗的測試**（沿用檔案裡的 `scriptedTools`、`reply`、`call`）
  - `testCustomExecutorAndLimit`：`definitions=[{"type": "function", "function": {"name": "x", "parameters": {}}}]`，`execute` 一律回 `tools.failed("壞")`，`maxCalls=6`，模型一直呼叫 `x`。斷言 `outcome.toolCalls == 6`、`outcome.exhausted`，而且 `fake.toolSets[0] == ["x"]`。
  - `testProposalStopsLoop`：`execute` 對 `p` 回 `ToolResult(True, [], [], False, None, None, {"kind": "booking.cancel"})`。模型回 `reply(call("p", {}), content="要取消嗎？")`。斷言 `outcome.proposal == {"kind": "booking.cancel"}`、`outcome.answer == "要取消嗎？"`、`len(fake.calls) == 1`、`outcome.result is None`。
  - `testOnlyFirstProposalIsKept`：同一個 reply 帶兩個 `p` call（第二個參數不同）。斷言 `execute` 只被呼叫一次、`len(outcome.steps) == 1`。
  - `testProposalWithoutTextUsesDefaultAnswer`：reply 的 content 是空字串。斷言 `outcome.answer == "請確認以下內容。"`。
- [ ] **Step 2: 執行，確認失敗**：`python -m pytest tests/qa/test_qa_agent.py -q`，應該出現 `TypeError: unexpected keyword argument 'definitions'`
- [ ] **Step 3: 實作**。`allowedTools` 的過濾改成作用在 `definitions` 上；結尾 `fallbackAnswer` 的判斷在有 `proposal` 時跳過。
- [ ] **Step 4: 執行 `python -m pytest tests/qa -q`**，全部通過，包含現有的 agent 與 jev 測試
- [ ] **Step 5: Commit**：`git commit -m "問答 agent：可指定工具、執行器與上限，提議就停"`

### Task 3: 提議工具與確認卡摘要

**Files:**
- Create: `backend/app/modules/qa/proposals.py`
- Test: `backend/tests/qa/test_qa_proposals.py`

**Interfaces:**
- Consumes: `SandboxData`（Task 1）、`tools.ToolResult`（Task 2）、`tools.ToolArgumentError`、`tools.parseRange`、`tools.requireText`、`tools.optionalText`、`tools.failed`
- Produces:
  - `@dataclass Asker: employeeId: int; name: str; department: str | None`
  - `findAsker(data: SandboxData, employeeId: int | None) -> Asker | None`
  - `formatRange(start: datetime, end: datetime) -> str`：跟前端 `forms/time.formatRange` 的輸出一樣
  - `proposalDefinitions: list[dict]`：5 個工具定義，名稱與參數照 spec 的表格
  - `executeProposal(data: SandboxData, asker: Asker | None, name: str, arguments: dict) -> ToolResult`：成功時回 `ToolResult(True, [], [], False, None, None, proposal)`；參數錯誤時回 `tools.failed(...)`
  - `proposalNames: set[str]`
- proposal 的形狀：

```
{"kind": str, "request": {"method": "POST"|"PATCH", "path": str, "body": dict | None},
 "summary": [{"label": str, "value": str}], "quote": {"path": str, "body": dict} | None}
```

- 規則：
  - **名稱比對**：完全相同的名稱優先；沒有的話用「包含」比對。對到 0 個時，錯誤是 `找不到「{text}」`。對到多個時，錯誤是 `「{text}」對到多個：{前 5 個名稱用、連接}，請問是哪一位／哪一個？`。
  - **時間**：`end <= start` 時錯誤是 `結束時間要晚於開始時間`。
  - **提問者**：`asker is None` 時，`propose_booking`、`propose_leave` 回 `你的帳號沒有員工資料，不能預約或請假`。
  - **參加者**：`participantEmployeeIds` 不含提問者，因為 service 會自動把提問者設成主辦人。
  - **路徑與 body**：
    - `booking.create`：`POST /api/booking/bookings`，body 是 `{title, category: "會議", startAt, endAt, resourceIds, participantEmployeeIds}`，有 note 時再加 note。
    - `booking.reschedule`：`PATCH /api/booking/bookings/{id}`，body 是 `{startAt, endAt}`。bookingId 必須在 `data.rows["bookings"]` 裡。
    - `booking.cancel`：`POST /api/booking/bookings/{id}/cancel`，body 是 `None`。
    - `leave.create`：`POST /api/leave/requests`，body 是 `{leaveTypeId, startAt, endAt, reason}`。`quote` 是 `{path: "/api/leave/requests/quote", body: 同一份}`。假別名稱用 `data.leaveTypes` 比對。
    - `leave.withdraw`：`POST /api/leave/requests/{id}/withdraw`，body 是 `None`。該筆申請在 `data.rows["leave_requests"]` 裡必須是提問者自己的（`employee_id`），而且 `status == "pending"`。不符合時錯誤是 `只能撤回自己待核准的申請`。
  - **summary**：
    - 預約類有 `標題`、`時間`、`參加者`（第一位寫「你」，其他人用姓名，以「、」連接）、`會議室`（沒有資源時寫「不預約」）。
    - 改時間的 `時間` 寫成 `{舊時間} → {新時間}`。
    - 請假類有 `假別`、`時間`、`原因`（沒有填時寫「（未填）」）。

- [ ] **Step 1: 寫失敗的測試**
  - 資料：沿用 `tests.qa.test_qa_tools.makeToolWorld`，另外在測試裡建 `B 會議室`（kind `room`、capacity 6）。用 `collectSandboxData(conn, w.bobActor, date(2026, 11, 21))` 取得 data，提問者是 bob；需要 alice 當提問者的測試，另外用 `w.aliceActor` 收集一次。
  - `testFormatRange`：`formatRange(datetime(2026, 11, 25, 14), datetime(2026, 11, 25, 15)) == "11/25（三）14:00–15:00"`；跨日的情況是 `"11/24（二）09:00 – 11/25（三）18:00"`。
  - `testFindAsker`：bob 的結果是 `Asker(w.bob, "bob", "工程部")`；`findAsker(data, None) is None`。
  - `testProposeBooking`：參數 `{"title": "討論", "start": "2026-11-25 14:00", "end": "2026-11-25 15:00", "participants": ["alice"], "resources": ["B 會議室"]}`。斷言：
    - `request == {"method": "POST", "path": "/api/booking/bookings", "body": {"title": "討論", "category": "會議", "startAt": "2026-11-25T14:00", "endAt": "2026-11-25T15:00", "resourceIds": [bRoom], "participantEmployeeIds": [w.alice]}}`
    - summary 的 `參加者` 是 `你、alice`，`時間` 是 `11/25（三）14:00–15:00`
  - `testAmbiguousNameListsCandidates`：participants 是 `["bo"]`。斷言 `not result.ok`、錯誤訊息同時包含 `bob` 和 `boss`、`result.proposal is None`。
  - `testExactNameWins`：participants 是 `["bob"]` 時只對到 bob（不會因為「boss」也包含 bo 而變成多個）。
  - `testProposalRejectsEmptyRange`：start 和 end 相同時，錯誤是 `結束時間要晚於開始時間`。
  - `testRescheduleAndCancelNeedKnownBooking`：用不存在的 bookingId（例如 99999）回錯誤；用週會的 id 時，reschedule 的 path 是 `/api/booking/bookings/{id}`、method 是 `PATCH`。
  - `testProposeLeaveHasQuote`：`{"leaveType": "事假", "start": "2026-11-25 09:00", "end": "2026-11-25 18:00"}`。斷言 `body["leaveTypeId"] == w.types["personal"]`，而且 `quote["body"] == request["body"]`。（假別名稱以 seed 實際的名稱為準；先在測試裡從 `data.leaveTypes` 找 `w.types["personal"]` 對應的名稱，不要寫死。）
  - `testWithdrawOnlyOwnPending`：bob 撤回 alice 的申請，錯誤是 `只能撤回自己待核准的申請`；alice 當提問者時成功，path 是 `/api/leave/requests/{id}/withdraw`。
  - `testNoEmployeeCannotBookOrLeave`：`asker=None` 時，兩個工具都回 `你的帳號沒有員工資料，不能預約或請假`。
- [ ] **Step 2: 執行，確認失敗**：`python -m pytest tests/qa/test_qa_proposals.py -q`，應該出現 `ModuleNotFoundError: app.modules.qa.proposals`
- [ ] **Step 3: 實作 `proposals.py`**。參數錯誤用 `ToolArgumentError` 拋出，在 `executeProposal` 統一接住、轉成 `tools.failed`。
- [ ] **Step 4: 執行，確認通過**
- [ ] **Step 5: Commit**：`git commit -m "問答助理：提議工具與確認卡摘要"`

### Task 4: 找空資源的工具與助理執行器

**Files:**
- Create: `backend/app/modules/qa/assistant.py`
- Test: `backend/tests/qa/test_qa_assistant.py`

**Interfaces:**
- Consumes: `tools.toolDefinitions`、`tools.executeTool`、`tools.runFixed`、`tools.parseRange`、`proposals.proposalDefinitions`、`proposals.executeProposal`、`proposals.proposalNames`
- Produces:
  - `maxAssistantToolCalls = 6`
  - `assistantToolDefinitions: list[dict]` = `tools.toolDefinitions` + `find_available_resources` + `proposals.proposalDefinitions`
  - `makeExecutor(data, asker) -> Callable[[Connection, str, dict | None], ToolResult]`
- `find_available_resources`：
  - 參數：`start`、`end`；`kind` 可省略，enum 是 `["room", "equipment", "vehicle"]`，description 要寫「會議室是 room」；`minCapacity` 可省略，是整數。
  - 用參數化 SQL 在沙盒上找 `resources` 中，沒有任何 `bookings` 與 `[start, end)` 重疊的資源。
  - 有 `minCapacity` 時，排除容量是 NULL 或小於 minCapacity 的資源。
  - 回傳欄位：`name, kind, location, capacity`，依 `capacity NULLS LAST, id` 排序。
- 執行器：名稱在 `proposalNames` 裡時呼叫 `executeProposal`（不碰 conn）；是 `find_available_resources` 時自己處理；其他名稱交給 `tools.executeTool`。參數不是 dict 時，跟 `executeTool` 一樣回 `參數不是合法的 JSON 物件`。

- [ ] **Step 1: 寫失敗的測試**
  - 資料：用 `makeToolWorld` 加上 B 會議室（capacity 6）建出沙盒。
  - `testAvailableResourcesExcludeBooked`：查 2026-11-26 10:30～11:00、kind 是 room，結果只有 `B 會議室`。
  - `testAvailableResourcesCapacity`：同一時段、minCapacity 是 10，結果是空的。
  - `testExecutorRoutesProposalAndQuery`：`run_sql` 照常有結果；`propose_cancel_booking` 回的結果帶 `proposal`。
  - `testAgentToolsUnchanged`：`[d["function"]["name"] for d in tools.toolDefinitions] == ["run_sql", "find_available_people", "get_busy_periods"]`，且 `"find_available_resources" not in tools.handlers`。
- [ ] **Step 2: 執行，確認失敗**：`python -m pytest tests/qa/test_qa_assistant.py -q`
- [ ] **Step 3: 實作 `assistant.py`**
- [ ] **Step 4: 執行，確認通過**
- [ ] **Step 5: Commit**：`git commit -m "問答助理：找空資源工具與執行器"`

### Task 5: 助理的 prompt、`assistant` 模式與 history

**Files:**
- Modify: `backend/app/modules/qa/prompt.py`、`backend/app/modules/qa/service.py`、`backend/app/modules/qa/router.py`
- Test: `backend/tests/qa/test_qa_service.py`、`backend/tests/qa/test_qa_api.py`

**Interfaces:**
- Consumes: Task 2 的 `runAgent` 參數、Task 3 的 `findAsker`、Task 4 的 `assistantToolDefinitions`、`makeExecutor`、`maxAssistantToolCalls`
- Produces:
  - `prompt.buildAssistantMessages(question: str, history: list[dict], data: SandboxData, now: datetime, asker: Asker | None) -> list[dict]`：順序是 system → history → `{"role": "user", "content": question}`
  - `service.modes = ("pipeline", "agent", "jev", "assistant")`
  - `service.ask(..., history: list[dict] | None = None)`：只有 assistant 模式會讀 history
  - `AskBody.history: list[dict] | None = None`
  - 回應：跟 agent 模式相同的欄位，再加 `proposal`（`dict | None`）。沒有查詢結果時，`sql` 是 `""`、`columns` 和 `rows` 是 `[]`、`truncated` 是 `False`。
- **system prompt 的內容**：
  - 工具原則沿用 agent 的 1、4、5、7 條。
  - 提問者段落：有員工資料時寫 `提問者：{name}（employee_id = {id}，{department}）`；沒有時寫 `提問者沒有員工資料，不能替他請假或當參加者`。
  - spec 的三條助理規則。
  - 挑會議室規則：沒指定會議室時，先用 `find_available_resources` 找容量至少是參加人數（含提問者）的會議室，取第一間。
  - 「（系統紀錄）開頭的訊息是系統告訴你使用者對確認卡做了什麼」。
  - 最後接 `contextSections(data, now)`。
- **history 驗證**：不是 list、超過 40 則、某一則不是 `{role, content}`、role 不是 user／assistant、content 不是字串或超過 1000 字，都回 `AppError("VALIDATION", "對話紀錄格式不對或太長", 422, {"field": "history"})`。驗證要在拿名額之前。
- **錯誤處理**：assistant 模式下 `answer` 是空字串、沒有 result、也沒有 proposal 時，回 `AppError("QA_QUERY_FAILED", "助理沒有給出回答，請換個說法再試", 422, {"steps": ...})`。

- [ ] **Step 1: 寫失敗的測試**
  - `test_qa_service.py`：
    - `testAssistantPromptHasAskerAndHistory`：`buildAssistantMessages("再來呢", [{"role": "user", "content": "嗨"}, {"role": "assistant", "content": "你好"}], data, now, Asker(...))`。斷言 system 內容包含 `提問者：bob（employee_id = `；`messages[1:] == [嗨, 你好, 再來呢]`。
    - `testAssistantPromptWithoutEmployee`：asker 是 None 時，system 包含 `提問者沒有員工資料`。
    - `testAssistantModeReturnsProposal`：fake toolLlm 依序回 `propose_cancel_booking(週會 id)`。斷言 `body["mode"] == "assistant"`、`body["proposal"]["kind"] == "booking.cancel"`、`body["rows"] == []`。
    - `testAssistantClarifyingReplyIs200`：模型直接回文字 `是哪一位林？`。斷言 `body["answer"] == "是哪一位林？"`、`body["proposal"] is None`。
    - `testAssistantUsesSixCalls`：模型一直呼叫 `run_sql` 錯誤的 SQL。斷言回 422 `QA_QUERY_FAILED`，而且 `len(details["steps"]) == 6`。
    - `testHistoryValidation`：以下各自回 422、`details.field == "history"`：41 則；一則 1001 字；role 是 `system`。
    - `testOtherModesIgnoreHistory`：agent 模式帶一則 role 是 system 的 history 時，仍然照常回答，不回 422。
  - `test_qa_api.py`：`testAskAssistantModeEndToEnd`：用 monkeypatch 換掉 `callModelWithTools`，POST `{"mode": "assistant", "history": [...]}`。斷言 200，而且 fake 收到的 messages 裡有 history 的內容。
- [ ] **Step 2: 執行，確認失敗**：`python -m pytest tests/qa/test_qa_service.py tests/qa/test_qa_api.py -q`
- [ ] **Step 3: 實作**。`resolveMode` 的錯誤訊息改成列出四種模式。新增 `runAssistantMode(sandboxConn, toolLlm, model, question, history, data, now, asker)`，呼叫 `runAgent(..., definitions=assistantToolDefinitions, execute=makeExecutor(data, asker), maxCalls=maxAssistantToolCalls)`。
- [ ] **Step 4: 執行 `python -m pytest tests/qa -q`**，全部通過
- [ ] **Step 5: Commit**：`git commit -m "問答助理：assistant 模式、提問者與對話紀錄"`

### Task 6: 前端助理模式與對話紀錄

**Files:**
- Modify: `frontend/src/api/types.ts`、`frontend/src/shell/SidePanel.tsx`、`frontend/src/shell/QaMessage.tsx`
- Test: `frontend/src/shell/sidePanel.test.tsx`

**Interfaces:**
- Produces:
  - `QaMode` 加上 `"assistant"`
  - `interface QaProposal { kind: "booking.create" | "booking.reschedule" | "booking.cancel" | "leave.create" | "leave.withdraw"; request: { method: "POST" | "PATCH"; path: string; body: Record<string, unknown> | null }; summary: { label: string; value: string }[]; quote: { path: string; body: Record<string, unknown> } | null }`
  - `QaAnswer.proposal?: QaProposal | null`
  - `interface QaHistoryItem { role: "user" | "assistant"; content: string }`
  - `ChatEntry` 加上 `{ id: number; kind: "note"; text: string }`（系統紀錄）
  - `toHistory(entries: ChatEntry[]): QaHistoryItem[]`（export，放在 `QaMessage.tsx`）：
    - `question` 轉成 user；`answer` 轉成 assistant（內容是 `result.answer`）；`note` 轉成 user；`pending` 和 `error` 略過。
    - 只取最後 40 則，每則截到 1000 字。
  - `SidePanel` 內部的 `addNote(text: string)`：Task 7 的確認卡用它補系統紀錄
- 規則：
  - 模式選單加上 `助理`（value 是 `assistant`）。
  - 只有在 assistant 模式時，請求才帶 `history: toHistory(發問前的 entries)`。
  - 新增按鈕 `清除對話`：清空 entries。
  - `note` 顯示成一行灰色小字。

- [ ] **Step 1: 寫失敗的測試**
  - `testToHistoryMapsAndTrims`：直接測 `toHistory`。45 則交錯的 question／answer 加上 1 則 note、1 則 error，輸出長度是 40、最後一則是 note、沒有 error；一則 1200 字的 question 會被截成 1000 字。
  - `testAssistantSendsHistory`：選助理模式後連問兩題。第二次請求的 body 是 `history: [{role: "user", content: 第一題}, {role: "assistant", content: 第一題的回答}]`。
  - `testAgentModeSendsNoHistory`：agent 模式的第二題，請求 body 沒有 `history`。
  - `testClearConversation`：按 `清除對話` 後，訊息都不見了，下一題的 history 是空陣列。
- [ ] **Step 2: 執行，確認失敗**：`cd frontend; npx vitest run src/shell/sidePanel.test.tsx`
- [ ] **Step 3: 實作**
- [ ] **Step 4: 執行 `npm test`**，全部通過
- [ ] **Step 5: Commit**：`git commit -m "問答面板：助理模式與對話紀錄"`

### Task 7: 確認卡

**Files:**
- Create: `frontend/src/shell/ProposalCard.tsx`、`frontend/src/modules/leave/MeetingWarning.tsx`
- Modify: `frontend/src/modules/leave/LeaveRequestForm.tsx`（改用搬出去的 `MeetingWarning`，行為不變）、`frontend/src/shell/QaMessage.tsx`、`frontend/src/shell/SidePanel.tsx`
- Test: `frontend/src/shell/proposalCard.test.tsx`

**Interfaces:**
- Consumes: Task 6 的 `QaProposal`、`addNote`；`useSubmit`、`apiSend`、`ConflictNotice`
- Produces: `ProposalCard({ proposal, active, onNote }: { proposal: QaProposal; active: boolean; onNote(text: string): void })`
- `SidePanel` 傳入 `active = (這則 answer 是最後一則帶 proposal 的 answer)`
- 卡片狀態：`open` → `done` / `cancelled` / `failed`。`done` 或 `cancelled` 之後按鈕消失。`active` 是 false，而且狀態還是 `open` 時，顯示 `已被新的提議取代`，按鈕消失。
- 確認：
  - 用 `useSubmit` 包 `apiSend(request.method, request.path, body)`，第二次按「仍要送出」時 body 加 `acknowledgeWarnings: true`。
  - invalidate：booking 類是 `[["bookings"], ["summary"]]`，leave 類是 `[["leave"]]`。
  - 成功時 `onNote(`（系統紀錄）使用者已確認，${完成文字} #${回應的 id}`)`。完成文字依 kind 是：`建立了會議`、`改了會議時間`、`取消了會議`、`送出了請假申請`、`撤回了請假申請`。
- 錯誤：
  - `RESOURCE_CONFLICT`、`PARTICIPANT_CONFLICT` 交給 `ConflictNotice`；`MEETING_CONFLICT` 交給 `MeetingWarning`。
  - 其他錯誤顯示 `error.message`，狀態變成 `failed`，並呼叫 `onNote(`（系統紀錄）送出失敗：${message}`)`。
- 取消：`onNote("（系統紀錄）使用者取消了這個提議")`。
- `leave.create`：卡片一出現就呼叫 quote，顯示 `時數 {hours} 小時`、`扣完剩 {remainingAfter} 小時`。quote 回的 `conflicts` 不是空的時，提示「這段時間你有會議」。quote 失敗時顯示錯誤，確認按鈕停用。

- [ ] **Step 1: 寫失敗的測試**（用 `renderApp` 與 mock routes，跟 sidePanel.test.tsx 一樣）
  - `testBookingConfirmCallsApiAndNotes`：確認後，`POST /api/booking/bookings` 收到的 body 等於 proposal 的 body；卡片顯示已完成；對話出現 `（系統紀錄）使用者已確認，建立了會議 #42`。
  - `testParticipantConflictThenOverride`：第一次回 409 `PARTICIPANT_CONFLICT`，畫面出現衝突提示；按「仍要排」後，第二次請求的 body 帶 `acknowledgeWarnings: true`。
  - `testLeaveCardShowsQuote`：quote 回 `{hours: 8, remainingAfter: 48, conflicts: []}`，畫面顯示 `8 小時` 與 `48 小時`。
  - `testCancelDoesNotCallApi`：按「取消」後，沒有呼叫任何寫入 API，對話出現 `（系統紀錄）使用者取消了這個提議`。
  - `testOlderProposalIsSuperseded`：連續兩則回答都帶 proposal，第一張卡顯示 `已被新的提議取代`，而且沒有確認按鈕。
  - `testConfirmErrorIsShown`：cancel API 回 404 `NOT_FOUND`，卡片顯示錯誤訊息，對話出現 `（系統紀錄）送出失敗：`。
  - 既有的 `leave.test.tsx` 要維持全綠，證明搬走 `MeetingWarning` 沒有改變請假表單的行為。
- [ ] **Step 2: 執行，確認失敗**：`npx vitest run src/shell/proposalCard.test.tsx`
- [ ] **Step 3: 實作**
- [ ] **Step 4: 執行 `npm test`**，全部通過
- [ ] **Step 5: Commit**：`git commit -m "問答面板：確認卡"`

### Task 8: README 與整體驗證

**Files:**
- Modify: `README.md`（在「問答」底下加「助理模式」一節：能做什麼、確認流程、限制、demo 腳本）

- [ ] **Step 1: 寫 README**。限制要寫：稽核紀錄分不出是不是助理建立的、提問者一定是主辦人、本機 3b 不穩定、對話不保存。
- [ ] **Step 2: 跑全部後端測試**：`cd backend; python -m pytest -q`，全部通過（約 6 分鐘，放背景跑）
- [ ] **Step 3: 跑全部前端測試**：`cd frontend; npm test`，全部通過
- [ ] **Step 4: 回歸測試**：用本機 3b 在背景跑 `cd backend; python -m evals.run --split dev --mode agent`，分數要跟 README 記錄的 10/40 一樣。記憶體不足被中止時，不要自己重跑，請使用者在自己的終端機執行。
- [ ] **Step 5: 估價**：demo 前先給使用者 Haiku 5.5 的估價，用 OpenRouter 的價格乘上 spec 的 demo 腳本約 10 輪、每輪最多 7 次模型呼叫來算。等使用者同意。
- [ ] **Step 6: 跑 demo**：用 `backend-host-8001` 跑 spec「怎麼驗證」的 1～9 步，在瀏覽器開 `127.0.0.1:8001`，每一步截圖。
- [ ] **Step 7: Commit**：`git commit -m "README：助理模式"`
