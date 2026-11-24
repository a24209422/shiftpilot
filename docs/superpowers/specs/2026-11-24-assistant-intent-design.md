# 設計：助理當唯一入口＋Jev 判斷意圖選工具組

## 為什麼做

最終想要的是：**使用者只管輸入，agent 自己判斷要查資料還是辦事。**

現況有兩個問題：

1. 問答面板要使用者自己在「舊流程／Agent／Agent＋Jev／助理」之間切換，面試官或一般使用者不會知道該選哪個。助理模式已經同時有查詢和提議工具（共 9 個），能當唯一入口。
2. 使用者決定**一定要用 Jev**。之前的 jev 模式是「Jev 選一個工具、只給模型那一個」，用在助理上會有問題：辦事幾乎都要先查詢（找空檔、查 id），而且多輪對話裡「訂 14:00 那個」這種回覆，單看一句判斷不出要做什麼。

這次改成：Jev 判斷**意圖**，每個意圖對應一組工具，組裡一定包含完成那件事要用的查詢工具；Jev 沒把握時退回 9 個全給。

已知的背景（見 README「agent vs agent＋Jev」）：選工具做到 40/40 時，Haiku 總分沒有變，瓶頸在 SQL 回傳的形狀，不在選工具。所以這次的目標**不是提高 Haiku 的分數**，而是：讓查詢不會誤觸提議工具、讓模型不會用錯提議工具、讓小模型面對的工具變少，以及在面板上讓人看到「先判斷意圖再動手」。

## 目標

1. 問答面板預設用新的「助理＋Jev」模式，一般使用者看不到模式選單；模式選單只在開發者模式顯示。
2. 新模式 `assistant-jev`：每一題（不是沿用的情況）先問 Jev 意圖，依意圖給模型一組工具；信心不夠、逾時、格式不對、或沒設 `JEV_API_KEY` 時，9 個工具全給。
3. 多輪對話中，上一輪是反問或還沒處理的提議時，沿用上一輪的意圖，不再問 Jev。
4. 面板的工具步驟裡顯示 Jev 判斷的意圖、信心，或是退回／沿用的原因。
5. 新增只呼叫 Jev 的意圖評測（仿 `python -m evals.route`），用它調 Jev 的選項說明。

## 不做

- 不改 `pipeline`、`agent`、`jev`、`assistant` 四種模式的行為；`assistant` 的 system prompt 一個字都不變，留著當「沒有 Jev」的對照組。
- 不做助理模式的完整評測（`evals.run --mode assistant` 或 `assistant-jev`）：之後另開子專案。
- 不做「提議後再請 Jev 檢查」：之前的 check 模式實測信心分不出好壞。
- 意圖評測只跑 dev，不打開 `heldout_cases.py`。
- 不把對話紀錄送給 Jev。

## 要避免的

- 查詢的問題被判成辦事、跳出確認卡；或辦事的問題被判成查詢，模型手上沒有提議工具卻回答「已幫你訂好」。
- 沒設 `JEV_API_KEY` 時整個面板不能用（舊的 jev 模式會回 503，新模式不能這樣）。
- 意圖說明照抄 dev 題目的字句。

## 做法比較

| 做法 | 取捨 | 結果 |
|---|---|---|
| **Jev 判斷一次意圖 → 給一組工具，沒把握退回全部** | 只多一次 Jev 往返；每組帶齊需要的查詢工具，辦事流程不會被卡住 | **採用** |
| Jev 分兩段：先分查詢／改動，再選工具 | 多一次往返（約 1.4 秒）、兩段錯誤會疊加；改動幾乎都要先查詢，第一段分不開工具 | 不採用 |
| Jev 只給一個工具（沿用 jev 模式） | 辦事要先查再提議，只給一個工具做不完 | 不採用 |
| Jev 判斷後只在 prompt 加提示，9 個工具全給 | 最不會出錯，但工具沒變少，Jev 對模型的作用很弱 | 不採用 |

## 設計

### 1. 入口與開發者模式

- 前端預設模式改成 `assistant-jev`。
- 模式選單只在開發者模式顯示，選項：舊流程、Agent、Agent＋Jev、助理、助理＋Jev。
- **開發者模式怎麼開（我的決定）**：網址帶 `?dev=1` 開啟、`?dev=0` 關閉，狀態記在 `localStorage`（例如 key `shiftpilot.dev`）。理由：demo 用的是建置好的前端（`backend-host-8001`），不能靠 `import.meta.env.DEV`；用網址切換不需要改權限或後端。專案目前沒有任何開發者模式，這是第一個。
- 關掉開發者模式時，一律送 `assistant-jev`，即使之前選過別的模式。
- 後端 API 沒帶 `mode` 時，預設從 `pipeline` 改成 `assistant-jev`（`QA_MODE` 仍可覆蓋）；`.env.example`、README 一起改說明。評測都會明確帶 mode，不受影響。

### 2. 意圖與工具組

| 意圖 id | 說明 | 工具 |
|---|---|---|
| `query` | 查詢或總結 | `run_sql`、`find_available_people`、`get_busy_periods`、`find_available_resources` |
| `booking` | 預約新會議 | `run_sql`、`find_available_people`、`get_busy_periods`、`find_available_resources`、`propose_booking` |
| `manageBooking` | 改期或取消既有會議 | `run_sql`、`find_available_people`、`get_busy_periods`、`find_available_resources`、`propose_reschedule_booking`、`propose_cancel_booking` |
| `leave` | 請假或撤回請假 | `run_sql`、`get_busy_periods`、`propose_leave`、`propose_withdraw_leave` |
| （退回） | Jev 沒選定 | 9 個全部 |

- `manageBooking` 與 `leave` 一定要有 `run_sql`：`bookingId`、`requestId` 只有它查得到（`get_busy_periods` 不回傳 id）。
- 工具組定義放在後端一個地方（例如 `qa/intent.py`），前端不需要知道。
- 工具次數上限沿用助理的 6 次。

### 3. 問 Jev

- 沿用 `jev.py` 的連線、遮 key、逾時、`JEV_MIN_CONFIDENCE` 門檻與退回原因（`unavailable`、`bad_response`、`low_confidence`），新增一個選意圖的函式（例如 `chooseIntent`），選項是上面 4 個意圖 id；`parseJevResponse` 要改成依呼叫端的選項清單驗證，不能寫死 `jevOptions`。
- 沒設 `JEV_API_KEY`：不呼叫 Jev，退回原因 `not_configured`，9 個工具全給（**不回 503**）。
- 送給 Jev 的內容跟現在一樣少：精簡日期參考＋這一題的問題文字＋選項說明。
- **選項說明的原則**（沿用 jev 的經驗）：每個選項只正面寫它做得到的事；「會議」「請假」這類兩邊都會出現的字，要用「查」和「辦」的動詞分開，例如 `query` 寫「查看、統計、列出會議或請假」，`booking` 寫「安排、預約一場新的會議」。說明的實際文字由實作時用意圖評測調出來。
- 現有 jev 模式的 `jevCriteria`、`chooseTool` 不改。

### 4. 沿用上一輪的意圖

- 回傳多一個 `intent` 物件：`{ name, confidence, fallbackReason, reused, promptTokens, seconds }`；`name` 是意圖 id，退回時是 `null`。
- 前端發問時，如果**上一則助理回覆**是以下兩種之一，就在 body 帶 `previousIntent`（上一則的 `intent.name`，退回時帶 `"all"`）：
  1. 只有文字、沒有表格也沒有提議（多半是反問）
  2. 帶提議，而且那張確認卡還沒被確認、取消或取代
- 上一則是查詢結果表格、確認卡已經處理過、或沒有上一則時，不帶 `previousIntent`，後端問 Jev。
- 判斷確認卡處理過了沒：`SidePanel` 在確認卡做完動作後會補一則系統紀錄（`addNote`），提議那則之後有系統紀錄、或它已不是 `activeProposalId`，就算處理過。
- 目前 `SidePanel` 只在 `mode === "assistant"` 時送 `history`；`assistant-jev` 也要送，後端的 `validateHistory` 也要對 `assistant-jev` 生效。
- 後端收到合法的 `previousIntent` 就直接用那一組工具，`intent.reused = true`，不呼叫 Jev；值不合法回 422。只有 `assistant-jev` 模式讀這個欄位。

### 5. System prompt

- 新增依工具組產生 prompt 的方式：`工具使用原則` 與 `助理規則` 裡提到特定工具的那幾條（找誰有空、看行程、run_sql、找會議室），只在那個工具有給的時候才放。
- 工具組是 `query`（沒有提議工具）時，多一條規則：「這題只能查資料；使用者其實想辦事的話，請他直接說要做什麼，不要說已經辦好。」
- 退回（9 個全給）時的 prompt 跟 `assistant` 模式一字不差。
- `buildAssistantMessages` 原本的輸出不能變（`assistant` 模式是對照組），新的參數要有預設值。

### 6. 面板顯示

- 工具步驟區塊沿用現在 jev 顯示 `route` 的位置，改成依 `intent` 顯示，例如：
  - 「Jev 判斷：預約會議（信心 0.92）」
  - 「沿用上一輪的意圖：預約會議」
  - 「Jev 沒選定（信心不夠），9 個工具都給」
  - 「沒設定 Jev，9 個工具都給」
- 意圖的中文名稱放前端。

### 7. 意圖評測

- 新增 `python -m evals.intent`（仿 `evals.route`）：只呼叫 Jev，不開資料庫、不跑 LLM，印出每題選了什麼、信心、對錯與花費，存一份結果檔。
- 題目：
  - 現有 dev 40 題全部標成 `query`（它們都是查詢題）。
  - 新增辦事題，放在新的檔案（例如 `evals/intent_cases.py`），只有 dev；`booking`、`manageBooking`、`leave` 各約 8 題，涵蓋不同說法（直接下指令、先問再辦、口語）。題目由我寫，寫好請你抽查。
- 單一題就能判斷的才放進評測；「訂 14:00 那個」這種要靠沿用規則的，用單元測試涵蓋。

## 驗收

1. 不開開發者模式：面板沒有模式選單，送出的 `mode` 是 `assistant-jev`。開 `?dev=1`：看得到 5 個選項；`?dev=0` 關掉後又看不到。
2. 有設 `JEV_API_KEY`、用 Haiku 5.5 在開發資料庫上（`backend-host-8001`）：
   - 問「明天誰有空？」→ 判成 `query`，回表格，沒有確認卡。
   - 說「幫我約林小美明天下午開會」→ 判成 `booking`，出現確認卡。
   - 助理反問後回一句短話 → 顯示「沿用上一輪的意圖」，沒有呼叫 Jev。
   - 「取消我明天的週會」、「我下週三想請特休」各跑一次，判成對的意圖並出現確認卡。
3. 拿掉 `JEV_API_KEY`：面板照常能用，顯示「沒設定 Jev，9 個工具都給」。
4. `python -m evals.intent` 在 dev 上：辦事題選對率與查詢題選對率都列出來；目標是查詢題不被判成辦事（避免誤跳確認卡）。實際數字跑出來再跟你討論，不預設門檻。
5. 後端與前端既有測試全過；`assistant` 模式的 prompt 有測試確認輸出不變。

## 留給實作決定

- 意圖相關程式放哪個檔案、函式怎麼切。
- `intent` 物件在 422 錯誤（查詢失敗）時也要一併回傳，跟現在 `route` 的做法一樣。
- 選項說明的實際文字（用意圖評測調，只看 dev）。
- 意圖評測結果檔的格式（仿 `evals.route`）。

## 我替你做的決定（請檢查）

1. 開發者模式用網址 `?dev=1`／`?dev=0` 切換，記在 `localStorage`。
2. 新模式叫 `assistant-jev`，原本的 `assistant` 保留不動當對照組。
3. 沒設 `JEV_API_KEY` 時不回 503，退回 9 個工具全給。
4. 沿用意圖由前端判斷上一則回覆的狀態、帶 `previousIntent`；確認卡處理過之後的下一題重新問 Jev。
5. `query` 工具組加一條「只能查資料」的規則，防止模型沒有提議工具卻說已辦好。
6. 意圖評測這次只有 dev，辦事題各約 8 題。
