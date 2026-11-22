# 設計：問答入口用 Jev 選工具（jev 模式）

日期：2026-11-22　｜　規模：子專案　｜　狀態：**待審閱**

前一份：`2026-11-22-qa-agent-design.md`（agent 模式）。這份不改 agent 模式，而是**新增第三種模式 `jev`**：先讓 Jev 選工具，再跑 agent 迴圈。三種模式可以切換，用同一份評測集比較。

## 目的與為什麼

1. **作品集**：展示「決策模型負責選路、LLM 負責填參數與寫回答」的分工，這是 agent 管線常見的做法。
2. **量出成本差**：使用者想知道接 Jev 之後變便宜還是變貴、差多少。Jev 本身很便宜（第三方資料：輸入 $0.042／百萬 tokens，輸出免費），真正的差別在 LLM 少用或多用了多少 tokens 和呼叫次數。
3. **可能拉高 3b 的分數**：agent 模式下 3b 是 dev 10/40，比 pipeline 的 20/40 低。失敗的原因有一部分是工具選錯，或該用工具卻沒用。

## 目標、非目標、反目標

**目標**

- 新增 `jev` 模式：Jev 先回答一題選擇題「這題該用哪個工具」，接著 agent 迴圈只拿到被選中的那個工具
- Jev 失敗或信心不足時，退回一般 agent 模式（三個工具都給），問答照常運作
- 評測可以跑 `--mode jev`，記錄每題 Jev 選了什麼、信心多少、有沒有退回、Jev 和 LLM 各用了多少 tokens
- README 補上 agent 和 jev 的對照表：分數、平均秒數、平均工具呼叫次數、LLM 與 Jev 各自的 tokens，以及換算出來的每題花費

**非目標**

- A1（用 Jev 在 pipeline 和 agent 之間選路）、B、C、D（迴圈中每一步都問 Jev、執行前把關、收尾判斷）
- 改 agent 模式或 pipeline 模式的行為、prompt
- 在 dev 題上標註「正確工具」來算 Jev 的選路準確率（題目檔要另外加欄位，之後再說）
- 讓 Jev 填參數或寫回答句

**反目標（做到了也算失敗）**

- 為了 Jev 改計分方式：計分照舊，只比對資料列
- 依 test 題調整選項說明或信心門檻：門檻只能用 dev 題決定，test 照舊只看總分，**不打開 `heldout_cases.py`**
- 把沙盒資料送給 Jev：Jev 只看得到問題文字、日期參考和工具說明，看不到任何資料列
- Jev 斷線或回錯格式時，問答整個失敗
- 沒先估價、沒經使用者同意，就呼叫雲端（包含 Jev）

## 限制

- Jev 還在搶先體驗。據 TypeSafe 文件，`questions` 回應格式還不穩定，可能沒有預告就改。所以程式要把 Jev 的回應格式集中在一個地方解析，解析失敗一律當作「退回 agent」
- Jev 的確切請求、回應欄位我還沒親眼確認。目前已知：走 chat completions 格式，model 是 `typesafe/jev-latest`，`response_format` 的 type 是 `questions`，回傳的是機率；OpenRouter 文件有 Jev 教學。所以實作順序第 1 步要先實際呼叫一次（見下方）
- key 放在 `.env` 的 `JEV_API_KEY`（已加好欄位）。如果 OpenRouter 能直接呼叫 Jev，改用現有的 `OPENROUTER_API_KEY`，`JEV_API_KEY` 留空即可
- 本機 3b 不用錢、雲端模型要花錢；Jev 每次都要花錢（極少）

## 做法比較

| 做法 | 取捨 | 結果 |
|---|---|---|
| A1. Jev 選 pipeline 或 agent | 改動小；但雲端 pipeline 的分數和花費沒量過，要多量一份基準；省錢的來源不明確 | 不採用 |
| **A2. Jev 直接選工具** | 省錢的來源明確（工具定義變少、少一輪猶豫）；直接對準 3b 選錯工具的弱點；能跟 agent 模式一對一比較 | **使用者選定** |
| B. 迴圈每一輪都問 Jev | 最能壓低選錯工具，但每輪多一次呼叫，迴圈要拆成兩段 | 不採用，A2 有效再考慮 |

## 設計

### 流程

```
問題 ─▶ Jev：選擇題「該用哪個工具？」
         │ 信心 ≥ 門檻 ─▶ agent 迴圈，tools 只給被選中的那一個
         │ 信心 < 門檻、呼叫失敗、格式不對 ─▶ agent 迴圈，三個工具都給（等於 agent 模式）
         ▼
      回答 + 表格 + steps + route
```

- Jev 的選項就是三個工具：`run_sql`、`find_available_people`、`get_busy_periods`，每個選項附一句中文說明（沿用 `tools.py` 裡 `toolDefinitions` 的說明）
- 給 Jev 的狀態：問題文字、`buildDateReference` 的日期參考、三個選項的說明。不給資料表說明、詞彙清單，也不給任何資料列（我的決定：選工具用不到這些，送得越少，越少資料離開本機）
- **只問一次**（我的決定：A2 的範圍）。迴圈中模型就算想換工具也換不了，只能用被選中的工具重試；這是要量的代價之一
- agent 迴圈本身不改：最多 4 次工具呼叫、表格是最後一次成功的結果、同樣的失敗處理。差別只有傳進去的 `tools` 清單
- system prompt 沿用 agent 模式的 `buildAgentMessages`（我的決定：只換工具清單，對照時才能看出是 Jev 造成的差別，而不是 prompt 不同。prompt 裡提到其他工具的指引留著，不另外裁剪）

### 信心門檻

- 預設 0.5（我的決定，可改）：最高的那個選項機率要 ≥ 門檻才採用
- 環境變數 `JEV_MIN_CONFIDENCE` 可以覆寫
- 門檻只能看 dev 的結果調整，見反目標

### 模型層

- `llm.py` 或另開 `jev.py`（留給實作者）新增 `chooseTool(question, now) -> JevDecision`
- `JevDecision`：`tool`（被選中的工具名，退回時是 `None`）、`confidence`、`fallbackReason`（`low_confidence`、`unavailable`、`bad_response`，或 `None`）、`promptTokens`、`seconds`
- **不丟例外**：任何錯誤都回傳 `tool=None` 加上原因，讓問答照常走 agent
- 逾時：10 秒（我的決定：Jev 宣稱很快，等太久就不如直接跑 agent）
- 重試：不重試（我的決定：失敗就退回，省得多等）
- 錯誤訊息要遮 key，跟現有 `callModel` 的做法一樣

### 切換模式

- `mode` 多一個值 `jev`；`QA_MODE` 也接受 `jev`
- 選了 `jev` 但 key 沒設：`QA_NOT_CONFIGURED`，503，訊息說要在 `.env` 填 `JEV_API_KEY`
- 回傳多一個 `route` 欄位：`{tool, confidence, fallbackReason, promptTokens, seconds}`；其他欄位跟 agent 模式一樣

### 問答面板

- 模式選單多一個選項「Agent＋Jev」，一律顯示；沒設 key 時選了會看到 503 的錯誤訊息（我的決定：不另外加「Jev 是否已設定」的 API）
- 步驟清單最上面多一行：「Jev 選了 find_available_people（信心 0.92）」；退回時顯示「Jev 沒選定（原因），三個工具都給」
- 其他顯示不變

### 評測

- `--mode jev`，結果檔名 `{split}-jev-{model}-時間.json`
- 每題多記：`route.tool`、`route.confidence`、`route.fallbackReason`、`jevPromptTokens`、`jevSeconds`
- 彙總多記：退回次數、各工具被選中的次數、Jev tokens 總數
- 花費換算：結果檔只存 tokens，不存價格；README 的對照表用當下查到的價格換算，寫明價格查詢日期與來源
- 計分函式不變；test 只看總分

### 費用控管

1. 第一次呼叫 Jev 前，先查 Jev **當下**的價格（TypeSafe 官方或 OpenRouter 模型頁），估價給使用者看，同意後才呼叫
2. 第一步只呼叫 1～3 次確認格式
3. 用本機 3b 跑 dev 的 avail 類別（7 題，`--filter`）：只有 Jev 要錢，估價後問使用者
4. 確認費用相符，再問要不要跑完整 dev、test，以及雲端模型（Haiku）的 jev 模式。雲端那份要分別估 Jev 與 LLM 的花費

## 實作順序（給寫計畫的人參考）

1. **先實際呼叫 Jev**（用完就丟）：確認走 OpenRouter 還是直接打 TypeSafe、請求欄位、回應裡機率的位置、tokens 用量欄位。結果寫回這份設計的「Jev 呼叫格式」小節，再開始寫程式。如果搶先體驗申請不到、OpenRouter 也沒有，停下來跟使用者討論
2. `chooseTool` 與測試（用假的 HTTP 回應測：正常、低信心、逾時、429、格式不對、選項名稱不在清單裡）
3. service 加 `jev` 模式與測試（退回時行為等於 agent 模式）
4. 評測 `--mode jev` 與新統計
5. 問答面板
6. 估價 → 使用者同意 → 3b avail 7 題 → 完整 dev、test → README 對照表
7. 雲端 Haiku 的 jev 模式：另外估價、另外問

## Jev 呼叫格式

（第 1 步完成後補上）

## 留給實作者決定的

- `chooseTool` 放在 `llm.py` 還是另開 `jev.py`
- 給 Jev 的選項說明文字（從 `toolDefinitions` 取，可縮短）
- 面板上 route 那一行的樣式
- 結果檔裡 route 欄位的確切結構
