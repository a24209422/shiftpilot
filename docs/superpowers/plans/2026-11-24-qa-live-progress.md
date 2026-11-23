# ShiftPilot 問答即時進度清單實作計畫

**目標**　使用者送出問題就看到一張進度卡，等候期間能辨認目前在準備資料、呼叫模型或執行工具。答案完成後可以回看這一題的步驟。

**設計依據**　使用者圈選的聊天內清單，以及討論中採用的真實執行進度。以下的 API 格式、收合方式、計時呈現是本計畫的實作建議。程式碼基準為 `af2ee4d`。

**架構**　沿用 FastAPI 的同步問答服務，在已有的工作邊界發送結構化事件。新端點使用 HTTP POST 與 UTF-8 NDJSON，一行一個事件。React 用 fetch 逐行讀取，在原位置更新同一張卡。原有 JSON 端點與評測程式繼續使用同一份問答邏輯。

**執行方式**　可用 superpowers:executing-plans 依序完成以下四項工作。每項先執行指定測試觀察新案例失敗，再實作、重跑、檢查差異並提交該項變更。

## 使用者會看到什麼

送出當下先顯示「正在送出」。伺服器接受問題後顯示「已收到問題」，隨後列出已發生的工作。例如「我今年還剩多少特休？」在一般查詢模式可以依序顯示「準備可查詢的資料」、「產生查詢」、「查詢資料」、「整理回答」。目前步驟顯示進行中圖示，完成打勾，失敗保留文字與圖示。首次查詢失敗、第二次成功，兩次記錄都留在原位。

進行中顯示經過秒數，終止後停止計時。成功時答案放在卡片下方，進度預設收合；錯誤時保留展開的步驟。助理直接反問時只列出實際發生的步驟。提議卡仍由使用者確認。進度文字取自固定的繁中標籤，計時器只負責顯示經過時間。

## 事件契約

新端點 `POST /api/qa/ask/stream` 與 `/api/qa/ask` 使用同一個 `AskBody`、session cookie、`X-App-Client: web` 和 `qa.ask`。每個請求獨享一條串流，回應類型為 `application/x-ndjson`。例如：

```jsonl
{"type":"accepted"}
{"type":"step","id":1,"stage":"prepare","state":"running"}
{"type":"step","id":1,"stage":"prepare","state":"done"}
```

- 每次實際工作取得新的整數 `id`，同一項工作以相同 ID 更新。`state` 為 `running | done | failed`。可重試步驟的 `failed` 只結束該次嘗試。各題的 ID 從 1 開始。
- `stage` 固定為 `prepare | route | generate_query | query | model | tool | proposal | compose`。一般工具用「執行查詢工具」，準備提議用「準備待確認的提議」。事件只傳種類、識別碼與狀態；模型推理內容、工具參數、SQL 與查詢列資料均不放進進度事件。
- 成功終止格式為 `{"type":"result","answer":<原有 QaAnswer>}`。失敗終止格式為 `{"type":"error","status":422,"error":{"code":"QA_QUERY_FAILED","message":"…","details":null}}`，沿用現有 AppError 結構。每次已接受的串流正常結束前恰有一個終止事件。
- 接受前的登入、權限、欄位、設定及併發錯誤沿用現有 HTTP 狀態和 JSON 錯誤格式。接受後的錯誤由終止事件傳遞。網路中斷若沒有終止事件，前端顯示「連線中斷，未收到完整回答」，結束動畫並保留已收到的步驟。

## 工作一　讓現有流程回報執行進度

**檔案**　新增 `backend/app/modules/qa/progress.py` 與 `backend/tests/qa/test_qa_progress.py`；修改同模組的 `service.py`、`agent.py`，補強 `test_qa_service.py`、`test_qa_agent.py`。

- [ ] 先以收集事件的回呼及假模型測試四種模式。pipeline 查詢重試應出現兩個不同的 query ID（第一次失敗、第二次完成）。agent 同一輪兩個工具應有各自的 ID。Jev 選不到工具時保留既有退回流程。assistant 直接反問不產生工具事件，產生提議時標示準備提議。斷言舊呼叫取得的答案、工具次數及既有 steps 均一致。
- [ ] 為 `service.ask` 加入選用的關鍵字參數 `onEvent`，預設無操作。進度物件限當次呼叫持有，負責編號及步驟結束。沿用原本驗證邏輯與 `questionSlot`；成功取得名額後、讀資料前送出 accepted。
- [ ] 在現有函式邊界發送事件。prepare 包住資料準備，route 包住 Jev 選擇，generate_query、query、compose 對應 pipeline 的三個呼叫。agent 迴圈每次呼叫模型使用 model；依實際工具與回傳的 `ToolResult.ok` 完成或標示失敗。遇到拒絕執行的工具以失敗狀態收尾。沿用各模式現有的重試上限、提議確認與備援答案。
- [ ] 在 `backend` 執行 `python -m pytest tests/qa/test_qa_progress.py tests/qa/test_qa_service.py tests/qa/test_qa_agent.py -q`，確認事件順序與舊有斷言均通過。

## 工作二　讓進度在答案完成前抵達瀏覽器

**檔案**　修改 `backend/app/modules/qa/router.py`；新增 `backend/app/modules/qa/stream.py`、`backend/tests/qa/test_qa_stream.py`。沿用 `app/infra/http.py` 的權限與 `app/infra/db.py` 的連線建立方式。

- [ ] 先寫一個能暫停假模型的測試。直接觀察 ASGI 的 `http.response.body`，讀到 model 或 generate_query 的 running 行才釋放假模型，然後收到 done 與唯一 result。以有逾時的同步事件協調，不以固定延遲判定。一般 TestClient 適合驗證完整內容，這一例須能觀察首段輸出。
- [ ] 新端點先完成現有的身份、權限與請求結構檢查。同步 worker 自行用應用程式的 databaseUrl 開啟及管理讀資料的連線，呼叫共用 `service.ask`；目前的 `connDependency` 會在端點返回時收尾，不可交給後續串流使用。保留 service 讀完資料、等待模型前即釋放該連線的行為。
- [ ] 用每請求專屬的事件佇列把 worker 的事件交給非同步回應（例如 `loop.call_soon_threadsafe` 通知 asyncio.Queue）。端點等待首項 accepted 或錯誤再決定回應型態，包含原始 accepted 行。接著用 StreamingResponse 即時寫出每行並設 `Cache-Control: no-store`。未預期例外記錄於伺服器並沿用通用錯誤文字。
- [ ] 斷線後停止發送，在下一個可中止的工作邊界結束；進行中的同步模型呼叫可等既有逾時或返回後收尾。名額由實際 worker 的 finally 釋放。確認重複發問仍回 429，斷線後沒有佇列寫入阻塞、殘留名額或未收尾的沙盒連線。
- [ ] 測未登入、缺 CSRF、無權限、無效輸入及額滿的 HTTP 回應。測兩位使用者同時發問各自只收到自己的事件、接受後例外只發一次 error、成功結果與原端點相同。在 `backend` 執行 `python -m pytest tests/qa/test_qa_stream.py tests/qa/test_qa_api.py tests/core/test_http_commit_timing.py -q`。

## 工作三　前端逐行接收與解析

**檔案**　修改 `frontend/src/api/client.ts`、`types.ts`；新增同目錄的 `qaStream.ts`、`qaStream.test.ts`。

- [ ] 以可控制的 ReadableStream 測試同一個 chunk 含多行、跨 chunk 的半行、繁中文字元拆成多段、先收到進度後才收到答案，以及首行前的 JSON 401。驗證既有 session 過期通知只觸發一次。測試非法事件、提前 EOF 和網路讀取失敗都能離開等待狀態。
- [ ] 定義與上方契約一致的判別聯集。提供 `askWithProgress(body, onProgress, signal): Promise<QaAnswer>`。與舊 client 共用送出標頭、憑證與 HTTP 錯誤處理。只發出一次 POST；等待資料用 reader 與增量 TextDecoder，保留尚未讀完的行，最後 flush；以類型守衛檢查事件，error 轉成既有 ApiError。
- [ ] 在 `frontend` 執行 `npm test -- src/api/client.test.ts src/api/qaStream.test.ts` 與 `npm run typecheck`。假串流的 result 尚未送出時，測試應已能觀察到 onProgress。

## 工作四　在同一則訊息顯示進度、答案或錯誤

**檔案**　修改 `frontend/src/shell/SidePanel.tsx`、`QaMessage.tsx`、`sidePanel.test.tsx`、`frontend/src/styles/global.css`；新增 `frontend/src/shell/QaProgress.tsx`。按需更新 `frontend/src/test/mockApi.ts` 的問答回應。

- [ ] 先寫面板互動測試。送出一次立即出現「正在送出」，推入 accepted 及 running 後顯示目前工作，暫停假串流仍看不到答案。推入 done 及 result 後同一則訊息顯示答案，展開可見已完成步驟。推入可復原的 failed 後再成功，卡片應保留該次失敗與最終答案。
- [ ] 擴充 `ChatEntry` 保存每題的時間與步驟，沿用 `pendingId` 定位訊息、`askingRef` 阻擋重複送出。accepted 前只顯示傳送中。固定標籤搭配圖示與文字，使用 ol、可操作的 details/summary 及簡短的狀態播報，經過秒數排除於即時播報區。元件卸載時停止計時並中止讀取。
- [ ] 保留答案表格、SQL、雲端標示、工具明細、提議確認與 `toHistory` 行為。串流終止錯誤保留既有錯誤訊息及 SQL 展開功能，未完成列停止轉動；連線中斷的列顯示「狀態未確認」。終止後能送出下一題，下一題的步驟從空清單開始。
- [ ] 更新既有問答互動測試的 mock 路徑及串流資料。在 `frontend` 執行 `npm test -- src/shell/sidePanel.test.tsx src/shell/proposalCard.test.tsx`、`npm test` 及 `npm run build`。窄面板 320px 驗收長標籤可換行、答案與輸入區仍可操作。

## 驗收與環境

| 情境 | 可觀察的通過條件 |
| --- | --- |
| 慢模型 | 模型仍被測試閘門暫停時，畫面已有一項執行中的工作；經過秒數增加，工作狀態維持原樣。 |
| 多次嘗試 | 第一次失敗與第二次成功各有一列；完成後可同時看到答案與嘗試紀錄。 |
| 助理直接追問或提議 | 清單只呈現實際呼叫；提議仍需按確認才會送出業務操作。 |
| 錯誤與中斷 | 受理前錯誤、執行中失敗及斷線各有清楚結果；卡片停止計時，輸入區恢復。 |
| 並行隔離 | 兩題的進度、結果與名額互不混用；重複送出維持既有的限制。 |

實作驗收在此 worktree 使用獨立測試環境、資料庫、連接埠及假模型。後端 fixture 會讀取 TEST_DATABASE_URL 與 QA_DB_PASSWORD；啟動整合測試前確認指向專用實例。若使用 Compose，分開專案名稱、主機連接埠和資料卷。最後用實際瀏覽器經開發代理送一題，確認每次工作進展都能在答案前顯示，並對照最終答案及錯誤。以上核取項目與測試指令均供後續實作使用。
