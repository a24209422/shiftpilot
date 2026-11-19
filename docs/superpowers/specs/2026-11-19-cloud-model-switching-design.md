# 設計：text2sql 可以切換本機／雲端模型

日期：2026-11-19　｜　規模：小型改動

## 目的

text2sql 現在只能用本機 Ollama 的小模型（qwen2.5:3b、qwen3-vl:4b-instruct），4b 在 test 集只有 62.5–70%。想接上便宜的雲端模型，在 app 和評測裡都能切換，之後用同一套評測量出「本機小模型 vs 雲端模型」的準確率差距，放進作品集。

雲端模型先放 Claude Haiku 5.5 和 GPT-6 Luna。使用者還沒申請 API key，所以這次只把功能做好、在 `.env` 留空位，不實際呼叫雲端 API、不跑雲端評測。

## 目標

- app「自然語言查詢」分頁有模型下拉選單，可以在本機和雲端模型之間切換
- 評測的 `--model` 可以指定雲端模型
- 本機 Ollama 保留，呼叫方式不變，README 的基準分數仍然有效

## 非目標

- 同一個問題讓多個模型並排回答
- 實際呼叫雲端 API、跑雲端模型的評測
- 記錄 token 用量與費用
- 讓雲端模型當預設模型

## 前置：先把 static rules 合併進 main

`exp/static-rules` 上還沒 commit 的 prompt 修改（規則 10–12、一個不帶日期的 few-shot）先 commit，重跑兩個本機模型的 dev 與 test，README 保留舊分數標成「加規則之前」並補上「加規則之後」，再 fast-forward 合併進 `main`，從 `main` 開 `feat/cloud-models`。test 只看總分。

## 做法比較

| 做法 | 取捨 | 結果 |
|---|---|---|
| OpenAI 相容格式 + OpenRouter | 一組 key 跑所有雲端模型，只寫一個函式；多經過一家公司，會收一點手續費 | **採用** |
| 同一個函式直連各家 OpenAI 相容端點 | 不經中間商，但每家要各申請 key | 不採用 |
| 只接一家的官方 SDK | 最直接，可用該家特有功能；換別家要重寫 | 不採用 |

## 使用者決定的事

1. 切換方式：「自然語言查詢」分頁的下拉選單，預設值是 `.env` 的 `OLLAMA_MODEL`；沒有 API key 時，選單裡不出現雲端模型
2. 雲端模型一律走 OpenRouter
3. `callOllama` 不改，雲端另外寫 `callOpenRouter`
4. 評測程式這次就支援雲端模型，但不跑；測試只用假的 HTTP 回應
5. 選單的模型清單寫在 `.env`：`LOCAL_MODELS`、`OPENROUTER_MODELS`、`OPENROUTER_API_KEY`（留空）。原本訂的名稱是 `OLLAMA_MODELS`，實作時發現它是 Ollama 自己用來指定模型存放資料夾的環境變數，所以改名
6. 呼叫參數：溫度 0、timeout 60 秒、不限制輸出長度、不送 `HTTP-Referer` / `X-Title`
7. 錯誤訊息：401 提示檢查 key、402 提示餘額不足、其他顯示狀態碼與內容；本機模型的訊息不變
8. `docker-compose.yml` 傳入三個新設定，沒填也能啟動
9. 資料（問題、資料表結構、資源名稱）送到雲端暫時沒關係；選單上的名稱後面標（本機）或（雲端）

## Claude 決定的細節

- 模型名稱在 `OPENROUTER_MODELS` 清單裡就走雲端，其他走本機（Ollama 的模型名稱也可能含 `/`，不能用 `/` 判斷）
- `OLLAMA_MODEL` 不在 `OLLAMA_MODELS` 裡時，放在選單最前面
- 評測指定雲端模型但沒有 key 時直接報錯，不會改用本機模型
- 選單的選擇只記在這次瀏覽，重新整理回到預設
- 頁面頂端說明列拿掉「text2sql 模型：…（Ollama）」，改由下拉選單顯示目前的模型
- 雲端回覆的 `content` 是 null 時（推理模型可能這樣），當成空字串，交給既有的「模型沒有產生 SQL」處理
- 其他 HTTP 錯誤的內容只顯示前 300 字，避免整頁 HTML 塞滿畫面

## 留給實作者

函式內部寫法、README 的確切措辭。
