# 排程助理（會動手的 agent）設計

日期：2026-11-22

## 為什麼做

作品集要讓面試官記住一件事：**跟傳統人資系統不一樣，用自然語言就可以查資料、總結資料、動手做事情。**

現在的問答（pipeline／agent／jev 三種模式）只會讀。問答 agent 的設計書（`2026-11-22-qa-agent-design.md`）刻意把寫入類工具列為非目標，這次補上。

順序（使用者決定）：**先做 demo，評測集之後另開子專案補。** 這次的設計要讓之後補評測集時不必重做（見「留給評測集」）。

## 目標

1. 側邊問答面板多一個「助理」模式：同一個對話框裡可以查、可以總結、可以辦事。
2. 能辦的事（使用者選的 B 方案）：
   - 會議預約：新增（沒指定會議室時自動挑一間空的）、改時間、取消
   - 員工請假：送出申請（先試算時數與餘額）、撤回申請
3. 能多輪對話：助理可以反問（「你說的林是林小美還是林志明？」），使用者可以接著回答（「訂 14:00 那個」）。
4. 動手前一定經過使用者確認；確認後走的是跟手動操作完全相同的 API。
5. demo 用雲端 Claude Haiku 5.5（經 OpenRouter）；選單照樣能選本機模型。

## 非目標

- 主管核准／駁回假單、人資排班、批次動作（C 方案，之後再說）
- 稽核紀錄標示「由助理建立」（做法 1 的已知缺點，使用者已接受）
- 對話存進資料庫、跨頁面重新整理後保留對話
- 一次回覆提議多個動作
- 串流輸出（streaming）
- 為本機 3b 調 prompt 讓它也穩定能辦事
- 這次不做「動作對不對」的評測集

## 反目標（做了也算失敗）

- 模型拿得到任何能寫入的資料庫連線，或任何寫入不經使用者按確認就發生
- 新增一條繞過現有 service 的寫入路徑（權限、衝突檢查、稽核都必須跟手動操作一樣）
- 改壞現有三種問答模式：`pipeline`、`agent`、`jev` 的行為與評測分數不能變
- 確認卡寫的內容跟實際送出的內容不一致

## 限制（現況）

- 問答在唯讀沙盒執行：`qa/sandbox.py` 把提問者看得到的資料複製進暫存表（今天前後各 90 天），模型的 SQL 只在那裡跑。
- `qa/agent.py` 的 `runAgent` 是自己寫的工具迴圈，最多 4 次工具呼叫；`/api/qa/ask` 一次一題、沒有前文。
- 模型目前**不知道提問者是誰**（記憶 qa-eval：「我的假」答不出來）。助理要能說「幫我請假」「我的會議」，這次必須補上。
- 寫入 API（全部已存在，這次不改）：
  - `POST /api/booking/bookings`（`BookingCreate`：title、category、startAt、endAt、resourceIds、participantEmployeeIds、organizerEmployeeId、note、acknowledgeWarnings）
  - `PATCH /api/booking/bookings/{id}`（改 startAt、endAt）
  - `POST /api/booking/bookings/{id}/cancel`
  - `POST /api/leave/requests/quote`、`POST /api/leave/requests`（`LeaveRequestBody`：leaveTypeId、startAt、endAt、reason、acknowledgeWarnings）
  - `POST /api/leave/requests/{id}/withdraw`
- 衝突提醒：參加者不方便回 409 `PARTICIPANT_CONFLICT`、請假時段有會議回 409 `MEETING_CONFLICT`，帶 `acknowledgeWarnings: true` 重送才會寫入。前端已有 `ConflictNotice` 元件。
- 改／取消會議只有建立者或有 `booking.writeAny` 的人可以（`canModify`），由 service 擋。
- 同時發問上限（每人 1 題、全站 3 題）照舊適用。
- 雲端呼叫要先估價、取得使用者同意才跑（記憶 qa-agent）。

## 做法比較

| 做法 | 內容 | 取捨 | 結果 |
|---|---|---|---|
| **1. 前端直接呼叫現有 API** | 助理只回傳「提議的動作」（API 路徑＋body＋給人看的摘要）；前端畫確認卡，按下確認後前端用同一份 body 呼叫現有 API | 不新增任何寫入程式；agent 沒有寫入權限。稽核分不出是不是助理建的 | **使用者選這個** |
| 2. 後端暫存提議＋新的確認 API | 提議存在伺服器，`POST /qa/actions/{id}/confirm` 由後端呼叫 service | 能標來源、能比對確認內容；但要多做暫存、過期、重複確認，多一條寫入路徑，換來的安全有限（使用者本來就能手動做） | 不選 |
| 3. agent 框架的 interrupt（如 LangGraph） | 用框架暫停等人確認 | 要重寫已有評測的 `runAgent`、多一個依賴，跟目標無關 | 不選 |

## 設計

### 整體流程

```
使用者：幫我跟黃志強、林小美約下週二下午一小時的會
  → 前端送 POST /api/qa/ask {mode: "assistant", model, question, history: [...]}
  → 後端：讀沙盒資料、在沙盒跑工具迴圈（查詢工具＋提議工具）
  → 回覆：{answer: "三人 14:00–15:00 都有空，要訂嗎？", proposal: {...}}
前端：顯示回答＋確認卡（標題、時間、參加者、會議室）
使用者按「確認」
  → 前端呼叫 POST /api/booking/bookings（body 就是 proposal.request.body）
  → 409 有衝突：卡片顯示衝突清單＋「仍要送出」（重送時帶 acknowledgeWarnings）
  → 成功：卡片變成「已建立」，對話紀錄補一句結果；時間軸等畫面重新抓資料
```

### 後端

**新模式 `assistant`**（我的決定）：加在 `qa/service.py` 的 `modes`，不改 `agent` 模式。理由：agent 模式已經有評測基準（3b dev 10/40、Haiku 33/40），助理加了提議工具和多輪對話，混在一起會讓舊分數失去可比性。

**API**：沿用 `POST /api/qa/ask`，`AskBody` 加上可省略的 `history`：

```
history: [{role: "user" | "assistant", content: str}]   # 不含這次的 question
```

- 只有 `mode == "assistant"` 時讀 `history`；其他模式忽略。
- 上限（我的決定）：後端最多收 40 則、每則 1000 字，超過回 422（只是防呆）。前端只送最近 40 則，所以正常使用不會碰到 422。理由：demo 一段對話約 15～20 則（每步提問、回答、動作結果各一則），40 則留了餘裕，又能控制送給模型的長度與費用。被截掉的舊訊息裡的 id，模型可以用查詢工具重新查。
- 動作結果（確認、取消、成功、失敗）在 history 裡是**獨立一則** `role: "user"`，內容以「（系統紀錄）」開頭，例如「（系統紀錄）使用者已確認，建立了會議 #42」（我的決定）。
- 伺服器不保存對話；每次請求都重建 system prompt＋history＋這次的 question。

**讓模型知道提問者**：assistant 模式的 system prompt 加一段「提問者：{姓名}（employee_id = {id}，部門 {部門}）」。資料從 `actor.employeeId` 對沙盒的 employees 取得。沒有 employee 的帳號（例如純管理員）寫「提問者沒有員工資料，不能替他請假或當參加者」。

**工具**：查詢工具沿用 `run_sql`、`find_available_people`、`get_busy_periods`。另外新增 1 個查詢工具、5 個提議工具，這 6 個都**只給助理模式用**，不加進 `tools.toolDefinitions`，所以 agent／jev 模式看到的工具不變。

新的查詢工具（使用者決定：約會議時自動挑會議室）：

| 工具 | 參數 | 做什麼 |
|---|---|---|
| `find_available_resources` | start、end、kind（資源種類，可省略，例如會議室）、minCapacity（可省略） | 固定寫好的參數化 SQL：找出這段時間沒有預約的資源，依容量由小到大排序 |

挑會議室的規則（寫在 prompt 裡）：使用者沒有指定會議室時，先用 `find_available_resources` 找出容量至少等於參加人數（含提問者）的空會議室，挑第一間放進提議。使用者有指定時就用他指定的那一間。確認卡會顯示挑到的會議室，使用者不滿意可以說「換一間」。

提議工具：

| 工具 | 參數 | 對應的 API |
|---|---|---|
| `propose_booking` | title、start、end、participants（姓名陣列，可省略）、resources（資源名稱陣列，可省略）、note（可省略） | `POST /api/booking/bookings` |
| `propose_reschedule_booking` | bookingId、start、end | `PATCH /api/booking/bookings/{id}` |
| `propose_cancel_booking` | bookingId | `POST /api/booking/bookings/{id}/cancel` |
| `propose_leave` | leaveType（假別名稱）、start、end、reason（可省略） | `POST /api/leave/requests`（確認卡先呼叫 quote） |
| `propose_withdraw_leave` | requestId | `POST /api/leave/requests/{id}/withdraw` |

提議工具**不寫任何東西**，只做三件事：
1. **檢查參數**：時間格式沿用 `tools.parseRange`；bookingId／requestId 必須存在於沙盒資料。
2. **名稱轉 id**：用沙盒資料（已在記憶體）把姓名、資源名、假別名轉成 id。比對規則跟查詢工具一致（部分名稱也可以）。找不到或對到多個時回工具錯誤，列出候選名稱，讓模型去反問使用者。
   - 假別：沙盒裡只有假別名稱，沒有 id。`collectSandboxData` 要另外讀 `leave_types`（id、名稱），放在 `SandboxData` 的新欄位。**不能改 `sandboxTables` 或 `schemaText`**，不然 pipeline／agent 的 prompt 會變，分數就不能比了。
   - 主辦人：現有 `createBooking` 沒帶 `organizerEmployeeId` 時，一律把提問者設成主辦人並列入名單。助理照這個規則走，不帶 `organizerEmployeeId`，所以提問者一定會參加。「幫 A、B 約，我不去」這次不支援（我的決定）。
   - 沒有員工資料的帳號：`propose_booking`、`propose_leave` 直接回工具錯誤「你的帳號沒有員工資料，不能預約或請假」，不產生提議（我的決定：送出也只會得到 422 `ORGANIZER_REQUIRED`）。
   - 時間格式：工具參數收 `YYYY-MM-DD HH:MM`（跟 `parseRange` 一樣），寫進 `request.body` 時要轉成寫入 API 的 `parseLocalTime` 接受的 `YYYY-MM-DDTHH:MM`。
3. **產生提議**：

```
proposal: {
  kind: "booking.create" | "booking.reschedule" | "booking.cancel" | "leave.create" | "leave.withdraw",
  request: {method: "POST" | "PATCH", path: "/api/booking/bookings", body: {...}},
  summary: [{label: "時間", value: "11/25（二）14:00–15:00"}, {label: "參加者", value: "你、黃志強、林小美"}, ...],
  quote: {path: "/api/leave/requests/quote", body: {...}} | null   # 只有 leave.create 有
}
```

`summary` 由後端從**同一份 body** 產生（名稱從沙盒資料反查），確保卡片寫的就是要送的（反目標第 4 點）。日期格式在 Python 寫一份跟前端 `forms/time` 一樣的格式（例如「11/25（二）14:00–15:00」）。`category` 固定填「會議」（我的決定：現有表單是自由文字欄位，沒有選項清單）。

**迴圈何時停**：
- 提議工具成功 → 這輪就停，不再呼叫模型；回答文字用模型在同一輪給的內容，沒有就用固定句（例如「請確認以下內容」）。理由：一次只提議一個動作，確認前不該繼續做事。
- 沒有提議、沒有查詢結果、只有文字回覆（例如反問）→ 照樣回 200，`answer` 是那段文字。這跟 agent 模式「沒有結果就 422」不同，因為多輪對話裡反問是正常的回答。
- 工具次數上限：助理模式 6 次，其他模式維持 4 次。理由：約會議至少要依序做「找人有空的時段 → 找空會議室 → 提議」三步，出錯重試一次就會超過 4 次。`runAgent` 要能從參數指定上限，預設值仍是 4。

**回傳**：跟 agent 模式相同的欄位（answer、steps、toolCalls、columns、rows…），加上 `proposal`（沒有時是 `null`）。

**prompt**（assistant 專用，`prompt.py` 新函式）：在 agent 的工具原則上加：
- 使用者要辦事時，先用查詢工具確認（例如找空檔），再呼叫提議工具；資訊不夠（時間、對象不明）就反問，不要猜。
- 提議工具只是「提議」，說明時要說「請確認」，不能說「已經訂好」。
- 使用者說要總結時，查出資料後用條列整理重點。

**模型**：demo 用 Haiku 5.5。`callModelWithTools` 已支援 OpenRouter 的 tool calling，history 以一般 user／assistant 訊息送出，不需要改模型層（如果實作時發現需要，算偏離設計，要回報）。

### 前端

- `SidePanel` 的模式選單加「助理」。選了助理時，每次發問把目前對話的文字紀錄當 `history` 送出（只送 question／answer 文字、以及動作結果的那一句，不送表格與工具步驟；回答帶提議時，answer 後面附上提議摘要，格式是「（提議：標題=週會；會議室=A 會議室…）」，讓模型知道自己上一輪提議了什麼）。
- 新元件「確認卡」（放在助理的回答下方）：
  - 顯示 `proposal.summary`；`leave.create` 先呼叫 `quote`，顯示時數與扣完後餘額（quote 回的衝突也先顯示出來）。
  - 「確認」：照 `proposal.request` 呼叫 API。409 衝突時，按「仍要送出」會在 body 加上 `acknowledgeWarnings: true` 重送。衝突畫面這樣處理：
    - 預約的衝突（`RESOURCE_CONFLICT`、`PARTICIPANT_CONFLICT`）直接用現有的 `ConflictNotice` 顯示。
    - 請假的衝突（`MEETING_CONFLICT`）`ConflictNotice` 不處理，所以把 `LeaveRequestForm.tsx` 裡的 `MeetingWarning` 拉出來共用（我的決定）。
    - 其他錯誤（403、409 重疊、422）在卡片上顯示錯誤訊息。
  - 「取消」：卡片變成「已取消」。
  - 成功後卡片變成「已完成」，並讓預約、請假、時間軸相關的 react-query 重新抓資料（demo 的重點：說完一句話，旁邊的時間軸就出現那場會）。
  - 確認、取消、成功、失敗都在對話紀錄補一則文字（例如「（使用者已確認，建立了會議 #42）」），下一輪送給模型。
  - 卡片處理完就不能再按；換一則新提議時，前一張還沒處理的卡片自動失效（顯示「已被新的提議取代」），避免同時有兩張能按的卡。
- 「清除對話」按鈕：清掉前文，重新開始。
- 本機模型選助理模式也能用，面板維持現有的「資料會送到廠商」標示規則。

### 留給評測集（這次不做，只是不要擋路）

- `proposal` 是結構化 JSON，之後評測可以直接比對 `kind` 與 `request.body` 跟標準答案。
- 評測的 `evals.run` 這次**不加** `--mode assistant`。

## 怎麼驗證（demo 腳本）

在開發資料庫、Haiku 5.5、助理模式下（用 `.claude/launch.json` 的 `backend-host-8001`，瀏覽器開 `127.0.0.1:8001`）：

1. 問「這個月我們部門誰請最多假？幫我整理一下」→ 用條列總結，不出現確認卡。
2. 說「幫我跟黃志強、林小美約下週二下午一小時的會」→ 助理找空檔、自動挑一間能坐 3 人的空會議室，給確認卡（時間、你＋兩人、會議室、類別「會議」）。先不要按確認，說「換一間」→ 給另一間會議室的新確認卡，舊卡片顯示「已被新的提議取代」。按新卡片的確認 → 時間軸出現那場會。
3. 說「改到 16:00」→ 給改時間的確認卡；按確認 → 時間軸更新。
4. 說「取消剛剛那場」→ 取消確認卡；按確認 → 會議消失。
5. 說「我下週三想請特休」→ 確認卡顯示試算時數與餘額；按確認 → 請假頁看得到待核准申請。
6. 說「撤回剛剛的假」→ 撤回確認卡；按確認 → 申請變成已撤回。
7. 說「幫我約林開會」（有兩個姓林的）→ 助理反問是哪一位，不出現確認卡。
8. 在確認卡按「取消」→ 資料沒有變動。
9. 用沒有 `booking.writeAny` 的帳號，要求取消別人建立的會議 → 確認後卡片顯示 403 的錯誤訊息，資料沒有變動。
10. pipeline、agent、jev 三種模式的後端測試全過；用本機 3b 跑一次 `--mode agent` 的 dev，分數跟目前 README 記錄的一致（不跑雲端，不花錢）。

雲端費用：Haiku 5.5 的 agent 評測（dev＋test）之前花不到 $0.10。我推估 demo 一次對話不到 $0.01，實作時第一次真的呼叫前要先估價、等使用者同意。

## 留給實作者決定的事

- 提議工具的 description 措辭、assistant prompt 的確切文字（要先在 dev 情境手動試，不能看 `heldout_cases.py`）
- 確認卡的版面與文字
- `summary` 的欄位順序
- 名稱比對多個結果時要列幾個候選
- 要重新抓哪些 react-query key
