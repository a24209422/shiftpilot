# 設計：直連 Google 的 Gemini API

日期：2026-11-19　｜　規模：小型改動　｜　前一份：`2026-11-19-cloud-model-switching-design.md`

## 目的

使用者訂閱 Google AI Pro，方案每月附 US$10 的 Google Cloud credits（在 Google AI Studio 領取），可以拿來付 Gemini API。這筆 credits 只能用在 Google 自己的 API，走 OpenRouter 用不到，所以要直連 Google。接上之後，Gemini 和本機模型、OpenRouter 上的模型一起放進切換選單與評測，做「價格 vs 準確率」比較。

## 目標

- 選單與評測 `--model` 可以選 Gemini（直連 Google）
- OpenRouter 的行為完全不變

## 非目標

- Claude 用使用者的 key 實際呼叫 API（key 由使用者填，第一次呼叫由使用者跑）
- Google 官方套件 `google-genai`、Gemini 特有功能（例如思考設定）
- 走 OpenRouter 上的 Gemini

## 做法比較

| 做法 | 取捨 | 結果 |
|---|---|---|
| 把現有雲端呼叫改成通用版：一張表列出各家的網址、key、模型清單、錯誤提示，共用一個呼叫函式 | 重試、空內容、缺 `choices` 的處理兩家共用；要改動已測過的 `callOpenRouter` 與測試 | **使用者選這個** |
| 另寫 `callGemini` | 不動現有程式，但邏輯會有兩份，日後只修一份就會不一致 | 不採用 |
| Google 官方套件 | 要新增套件、訊息格式不同，特有功能目前用不到 | 不採用 |

## 決定（Claude 提議、使用者同意）

- 端點：`https://generativelanguage.googleapis.com/v1beta/openai/chat/completions`（OpenAI 相容格式），header `Authorization: Bearer <key>`
- `.env`：`GOOGLE_AI_API_KEY=`（留空）、`GOOGLE_AI_MODELS=gemini-3.5-flash-lite,gemini-3.8-flash`。不用官方慣用的 `GEMINI_API_KEY`：Gemini CLI 等工具也讀這個名字，系統層級設了就會蓋過 `.env`（同 `OLLAMA_MODELS` 的教訓）。模型 ID 要等第一次呼叫才能確認
- 選單標籤：跟其他雲端模型一樣標（雲端）
- 錯誤提示：403「請確認 AI Studio 已綁定帳單，而且 key 屬於有 credits 的專案」；429「額度用完或呼叫太頻繁，請到 AI Studio 查看用量」；其他狀態碼顯示原文前 300 字（key 錯誤時 Google 回 400，原文就說得很清楚）
- 呼叫參數與重試跟 OpenRouter 相同：溫度 0、timeout 60 秒、429 與 5xx 等 2、4 秒重試，最多 3 次
- 評測 `--model` 可以指定 Gemini；沒有 key 時錯誤訊息指出要填哪個變數
- `docker-compose.yml` 傳入兩個新設定；`.env`、`.env.example` 多一行空白的 key
- README 寫上 Google 那邊要做的事：到 AI Studio 領 credits、綁定帳單（第三方資料說可能要先預付 US$5，未確認）、建立 API key
- 測試只用假的 HTTP 回應
- 從 `main` 開 `feat/google-gemini`

## Claude 決定的細節

- 同一個模型名稱同時列在 `OPENROUTER_MODELS` 和 `GOOGLE_AI_MODELS` 時，以表中先列的 OpenRouter 為準，選單只出現一次
- 各家獨立：只填 Google 的 key，選單就只多出 Google 的模型

## 留給實作者

函式內部寫法、README 的確切措辭。
