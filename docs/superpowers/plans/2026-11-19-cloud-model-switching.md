# text2sql 切換本機／雲端模型 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 先把 static rules 合併進 `main`，再讓 app 與評測可以在本機 Ollama 和 OpenRouter 上的雲端模型之間切換。

**Architecture:** `text2sql.py` 新增模型清單（讀 `.env`）、`getProvider` / `getLlm` 決定呼叫哪個函式，以及新的 `callOpenRouter`（OpenAI 相容格式）。`answerQuestion` 本來就接受 `llm` 參數，app 和評測只要改成傳入 `getLlm(選到的模型)`。`callOllama` 不動。

**Tech Stack:** Python 3.13、Streamlit、requests、PostgreSQL 17（Docker）、pytest、Ollama、OpenRouter

**Spec:** `docs/superpowers/specs/2026-11-19-cloud-model-switching-design.md`

## Global Constraints

- 縮排 2 個空白；函式與變數用 camelCase；註解用正體中文，只寫「為什麼」
- 不新增套件：OpenRouter 用現有的 `requests` 呼叫
- `callOllama`、`getOllamaConfig` 的內容一行都不改
- OpenRouter 端點：`https://openrouter.ai/api/v1/chat/completions`；body 只有 `model`、`messages`、`temperature: 0`；`timeout=60`；header 只有 `Authorization: Bearer <key>`（不送 `HTTP-Referer`、`X-Title`，不設 `max_tokens`）
- `.env` 變數名稱與 `.env.example` 預設值：`OLLAMA_MODELS=qwen2.5:3b,qwen3-vl:4b-instruct`、`OPENROUTER_API_KEY=`（空）、`OPENROUTER_MODELS=anthropic/claude-haiku-5.5,openai/gpt-6-luna`
- 選單標籤：`<模型>（本機）`、`<模型>（雲端）`，括號是全形
- 測試絕對不能真的呼叫 OpenRouter；`conftest.py` 會載入真正的 `.env`，所以碰到模型設定的測試都要用 `modelEnv` fixture 把四個變數清掉再設定
- 評測的 test 集只看總分，不打開 test 報告看每題細節
- 每個 commit 訊息用正體中文，結尾加 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`；不 push

## Review Focus

1. `.env` 清單有空白、多餘逗號或空字串 → 解析乾淨，選單不會出現空白選項（Task 3：`testParseModelListIgnoresSpacesAndEmptyItems`）
2. API key 沒填或只有空白 → 選單沒有雲端模型；評測指定雲端模型時，在連資料庫之前就報錯（Task 3：`testListModelsHidesCloudModelsWithoutApiKey`；Task 5：`testMainRejectsCloudModelWithoutApiKey`）
3. 雲端回覆的 `content` 是 `null`（推理模型可能這樣）→ 當成空字串，走既有的「模型沒有產生 SQL」，不會 `TypeError`（Task 3：`testCallOpenRouterTreatsNullContentAsEmpty`）
4. OpenRouter 回 502 之類的整頁 HTML → 錯誤訊息只取前 300 字（Task 4：`testDescribeLlmErrorTruncatesOtherHttpErrors`）
5. 雲端模型名稱含 `/` → 評測報告檔直接放在輸出資料夾，不會變成子資料夾（Task 5：`testMainUsesOpenRouterForCloudModel`）

---

### Task 1: commit static rules

分支：`exp/static-rules`（目前 `main` 和它指向同一個 commit `9cc2fe4`，static rules 只是還沒 commit 的修改）

**Files:**
- Modify（已經改好，只需 commit）：`text2sql.py`、`tests/test_text2sql.py`

- [ ] **Step 1: 確認 PostgreSQL 容器在跑，執行全部測試**

Run: `python -m pytest -q`
Expected: 全部 PASS

- [ ] **Step 2: Commit**

```bash
git add text2sql.py tests/test_text2sql.py
git commit -m "prompt 加入靜態規則：PostgreSQL 時長、現在時間、多資源子查詢，加一個不帶日期的 few-shot"
```

---

### Task 2: 重跑本機評測、更新 README、合併進 main

**Files:**
- Modify: `README.md`（「基準分數」一節）

- [ ] **Step 1: 重跑 dev（qwen2.5:3b 約 3 分鐘、4b 約 8 分鐘）**

Run:
```bash
python -m evals.run --model qwen2.5:3b
python -m evals.run --model qwen3-vl:4b-instruct
```
Expected: 每次最後印出各類別與 `total` 分數。記下兩個模型各類別的分數、總分，以及平均每題秒數（從報告 JSON 的 `results[].seconds` 計算，排除第一題）

- [ ] **Step 2: 重跑 test，只記總分**

Run:
```bash
python -m evals.run --split test --model qwen2.5:3b
python -m evals.run --split test --model qwen3-vl:4b-instruct
```
Expected: 只記 `total` 那一行，不打開 test 報告檔

- [ ] **Step 3: 檢查點**

如果任一個模型的 dev 總分低於加規則之前（3b 25、4b 41），停下來回報使用者，不要合併。否則繼續。

- [ ] **Step 4: 更新 README**

- 把 `### 基準分數（2026-11-18，PostgreSQL，溫度 0）` 改成 `### 基準分數：加規則之前（2026-11-18，PostgreSQL，溫度 0）`，內容不動
- 在它後面、`### 和改成多對多之前比較（SQLite 時期）` 前面，新增 `### 加入靜態規則之後（2026-11-19）`：
  - 改了什麼：規則 10（不要用 SQLite 函式、時長用 `EXTRACT(EPOCH ...)`）、規則 11（「現在」「下一個」「正在進行」的比較方式）、規則 12（兩個資源一起參與的排程用 `event_id IN (子查詢)`），以及一個不帶日期的 few-shot（避免小模型照抄日期條件）
  - 一張總分表：兩個模型 dev、test 的「之前 → 之後」
  - 一張 dev 各類別表：欄位是類別、題數、3b 之前 → 之後、4b 之前 → 之後，最後一列是平均每題秒數
  - 一句說明：test 一題是 4.2 個百分點，同一個模型重跑本來就會有幾題對錯互換，±2 題以內不足以判斷有沒有改善

- [ ] **Step 5: Commit README，合併進 main，開新分支**

```bash
git add README.md
git commit -m "README 記錄加入靜態規則前後的評測分數"
git checkout main
git merge --ff-only exp/static-rules
git checkout -b feat/cloud-models
```
Expected: `git log --oneline -3` 最上面兩個是剛才的兩個 commit，目前在 `feat/cloud-models`

- [ ] **Step 6: Commit 設計文件與計畫**

```bash
git add docs/superpowers/specs/2026-11-19-cloud-model-switching-design.md docs/superpowers/plans/2026-11-19-cloud-model-switching.md
git commit -m "新增切換本機／雲端模型的設計文件與實作計畫"
```

---

### Task 3: 模型清單與 OpenRouter 呼叫

**Files:**
- Modify: `text2sql.py`（`getOllamaConfig` 之後新增函式；`callOllama` 不動）
- Modify: `tests/conftest.py`（新增 `modelEnv` fixture）
- Modify: `.env.example`（`OLLAMA_MODEL` 那一行後面）
- Modify: `.env`（只在結尾補上缺少的變數，不改既有內容，不 commit）
- Test: `tests/test_text2sql.py`

**Interfaces:**
- Produces:
  - `openRouterUrl = "https://openrouter.ai/api/v1/chat/completions"`（模組常數）
  - `parseModelList(text: str | None) -> list[str]`
  - `getOpenRouterConfig() -> dict`：`{"apiKey": str（已 strip）, "models": list[str]}`
  - `listModels() -> list[str]`：本機模型（`OLLAMA_MODELS`，`OLLAMA_MODEL` 不在其中時放最前面；沒設定 `OLLAMA_MODELS` 時只有 `OLLAMA_MODEL`，預設 `qwen2.5:3b`），有 key 時再接上 `OPENROUTER_MODELS`，保留順序並去除重複
  - `getProvider(model: str) -> str`：在 `OPENROUTER_MODELS` 裡回 `"openrouter"`，否則 `"ollama"`
  - `getLlm(model: str) -> functools.partial`：`partial(callOpenRouter, model=model)` 或 `partial(callOllama, model=model)`，呼叫方式是 `llm(messages) -> str`
  - `callOpenRouter(messages: list[dict], model: str, apiKey: str | None = None) -> str`：`apiKey` 預設讀 `getOpenRouterConfig()`
  - fixture `modelEnv`：清掉 `OLLAMA_MODEL`、`OLLAMA_MODELS`、`OPENROUTER_API_KEY`、`OPENROUTER_MODELS`，回傳 `setEnv(**values)` 用來設定

- [ ] **Step 1: 在 `tests/conftest.py` 新增 fixture**

```python
modelEnvNames = ["OLLAMA_MODEL", "OLLAMA_MODELS", "OPENROUTER_API_KEY", "OPENROUTER_MODELS"]


@pytest.fixture
def modelEnv(monkeypatch):
  # 上面的 load_dotenv 會載入真正的 .env，使用者填了 key 之後測試結果不能跟著變
  for name in modelEnvNames:
    monkeypatch.delenv(name, raising=False)

  def setEnv(**values):
    for name, value in values.items():
      monkeypatch.setenv(name, value)

  return setEnv
```

- [ ] **Step 2: 在 `tests/test_text2sql.py` 寫會失敗的測試**

```python
cloudModels = "anthropic/claude-haiku-5.5,openai/gpt-6-luna"


class FakeResponse:
  def __init__(self, payload):
    self.payload = payload

  def raise_for_status(self):
    pass

  def json(self):
    return self.payload


def makeFakePost(content):
  calls = []

  def fakePost(url, **kwargs):
    calls.append({"url": url, **kwargs})
    return FakeResponse({"choices": [{"message": {"content": content}}]})

  fakePost.calls = calls
  return fakePost


def testParseModelListIgnoresSpacesAndEmptyItems():
  assert text2sql.parseModelList(" qwen2.5:3b, ,qwen3-vl:4b-instruct,") == ["qwen2.5:3b", "qwen3-vl:4b-instruct"]
  assert text2sql.parseModelList("") == []
  assert text2sql.parseModelList(None) == []


def testListModelsHidesCloudModelsWithoutApiKey(modelEnv):
  modelEnv(OLLAMA_MODEL="qwen2.5:3b", OLLAMA_MODELS="qwen2.5:3b,qwen3-vl:4b-instruct",
           OPENROUTER_API_KEY="   ", OPENROUTER_MODELS=cloudModels)
  assert text2sql.listModels() == ["qwen2.5:3b", "qwen3-vl:4b-instruct"]


def testListModelsAddsCloudModelsWhenApiKeySet(modelEnv):
  modelEnv(OLLAMA_MODEL="qwen2.5:3b", OLLAMA_MODELS="qwen2.5:3b,qwen3-vl:4b-instruct",
           OPENROUTER_API_KEY="test-key", OPENROUTER_MODELS=cloudModels)
  assert text2sql.listModels() == [
    "qwen2.5:3b", "qwen3-vl:4b-instruct", "anthropic/claude-haiku-5.5", "openai/gpt-6-luna",
  ]


def testListModelsPutsDefaultModelFirstWhenMissingFromList(modelEnv):
  modelEnv(OLLAMA_MODEL="llama3:8b", OLLAMA_MODELS="qwen2.5:3b,qwen2.5:3b")
  assert text2sql.listModels() == ["llama3:8b", "qwen2.5:3b"]


def testListModelsFallsBackToDefaultModel(modelEnv):
  assert text2sql.listModels() == ["qwen2.5:3b"]


def testGetProviderUsesOpenRouterListOnly(modelEnv):
  modelEnv(OPENROUTER_MODELS="anthropic/claude-haiku-5.5")
  assert text2sql.getProvider("anthropic/claude-haiku-5.5") == "openrouter"
  # Ollama 的模型名稱也可能有斜線，不在清單裡就是本機模型
  assert text2sql.getProvider("hf.co/someone/model") == "ollama"
  assert text2sql.getProvider("openai/gpt-6-luna") == "ollama"


def testGetLlmRoutesByProvider(modelEnv):
  modelEnv(OPENROUTER_MODELS=cloudModels)
  cloudLlm = text2sql.getLlm("openai/gpt-6-luna")
  localLlm = text2sql.getLlm("qwen2.5:3b")
  assert cloudLlm.func is text2sql.callOpenRouter
  assert cloudLlm.keywords == {"model": "openai/gpt-6-luna"}
  assert localLlm.func is text2sql.callOllama
  assert localLlm.keywords == {"model": "qwen2.5:3b"}


def testCallOpenRouterSendsChatRequest(monkeypatch, modelEnv):
  modelEnv(OPENROUTER_API_KEY="test-key")
  fakePost = makeFakePost("```sql\nSELECT 1\n```")
  monkeypatch.setattr(text2sql.requests, "post", fakePost)
  messages = [{"role": "user", "content": "問題"}]

  reply = text2sql.callOpenRouter(messages, model="openai/gpt-6-luna")

  call = fakePost.calls[0]
  assert reply == "```sql\nSELECT 1\n```"
  assert call["url"] == "https://openrouter.ai/api/v1/chat/completions"
  assert call["headers"] == {"Authorization": "Bearer test-key"}
  assert call["json"] == {"model": "openai/gpt-6-luna", "messages": messages, "temperature": 0}
  assert call["timeout"] == 60


def testCallOpenRouterTreatsNullContentAsEmpty(monkeypatch, modelEnv):
  modelEnv(OPENROUTER_API_KEY="test-key")
  monkeypatch.setattr(text2sql.requests, "post", makeFakePost(None))
  assert text2sql.callOpenRouter([{"role": "user", "content": "問題"}], model="openai/gpt-6-luna") == ""
```

- [ ] **Step 3: 確認測試失敗**

Run: `python -m pytest tests/test_text2sql.py -q -k "ModelList or ListModels or Provider or GetLlm or OpenRouter"`
Expected: FAIL，`AttributeError: module 'text2sql' has no attribute 'parseModelList'`（或其他還沒實作的名稱）

- [ ] **Step 4: 在 `text2sql.py` 實作 Interfaces 列出的常數與函式**

在 `callOllama` 後面新增。`callOpenRouter` 回傳 `response.json()["choices"][0]["message"]["content"] or ""`，並在這裡註解原因：推理模型可能回 null。呼叫前先 `raise_for_status()`。

- [ ] **Step 5: 確認測試通過，全部測試也沒壞**

Run: `python -m pytest -q`
Expected: 全部 PASS

- [ ] **Step 6: 更新 `.env.example` 與 `.env`**

`.env.example` 在 `OLLAMA_MODEL=qwen2.5:3b` 後面加：

```
# 「自然語言查詢」選單裡的本機模型；OLLAMA_MODEL 是預設選項
OLLAMA_MODELS=qwen2.5:3b,qwen3-vl:4b-instruct
# 雲端模型（透過 OpenRouter，到 openrouter.ai 申請 key）。key 留空時選單只會出現本機模型
# 用雲端模型時，問題、資料表結構和資源名稱會送到 OpenRouter，再轉給模型的廠商
OPENROUTER_API_KEY=
OPENROUTER_MODELS=anthropic/claude-haiku-5.5,openai/gpt-6-luna
```

`.env`：先用 `grep -c "^OLLAMA_MODELS=\|^OPENROUTER_API_KEY=\|^OPENROUTER_MODELS=" .env` 檢查有哪些變數已經存在（不印出內容），只在檔案結尾補上缺少的那幾行（同上面的內容）。不改既有的行，不 commit。

- [ ] **Step 7: Commit**

```bash
git add text2sql.py tests/conftest.py tests/test_text2sql.py .env.example
git commit -m "新增模型清單與 OpenRouter 呼叫，依模型名稱決定走本機或雲端"
```

---

### Task 4: app 加模型下拉選單、錯誤訊息、Docker 設定

**Files:**
- Modify: `text2sql.py`（新增 `describeModel`、`describeLlmError`）
- Modify: `app.py:69`（頁首說明列）、`app.py:72-90`（「自然語言查詢」分頁）
- Modify: `docker-compose.yml`（app 的 `environment`）
- Modify: `README.md`（「執行」一節、「結構」表的 `text2sql.py` 那一列）
- Test: `tests/test_text2sql.py`

**Interfaces:**
- Consumes: Task 3 的 `listModels()`、`getProvider(model)`、`getLlm(model)`、`getOllamaConfig()`、fixture `modelEnv`
- Produces:
  - `describeModel(model: str) -> str`：`"<model>（雲端）"` 或 `"<model>（本機）"`
  - `describeLlmError(error: requests.RequestException, model: str) -> str`，文字固定如下：
    - 本機模型（不管有沒有 response）：`f"無法呼叫 Ollama：{error}\n\n請確認 Ollama 已啟動，且已下載 {model}。"`
    - 雲端、HTTP 401：`"無法呼叫 OpenRouter（HTTP 401）：API key 錯誤，請確認 .env 的 OPENROUTER_API_KEY"`
    - 雲端、HTTP 402：`"無法呼叫 OpenRouter（HTTP 402）：OpenRouter 餘額不足"`
    - 雲端、其他 HTTP 狀態：`f"無法呼叫 OpenRouter（HTTP {status}）：{response.text[:300]}"`
    - 雲端、沒有 response（連線失敗、逾時）：`f"無法呼叫 OpenRouter：{error}"`

- [ ] **Step 1: 寫會失敗的測試**

```python
def makeHttpError(statusCode, body):
  response = requests.Response()
  response.status_code = statusCode
  response._content = body.encode("utf-8")
  return requests.HTTPError(f"{statusCode} Error", response=response)


def testDescribeModelMarksCloudAndLocal(modelEnv):
  modelEnv(OPENROUTER_MODELS="openai/gpt-6-luna")
  assert text2sql.describeModel("openai/gpt-6-luna") == "openai/gpt-6-luna（雲端）"
  assert text2sql.describeModel("qwen2.5:3b") == "qwen2.5:3b（本機）"


def testDescribeLlmErrorExplainsOpenRouterAuthAndCredit(modelEnv):
  modelEnv(OPENROUTER_MODELS="openai/gpt-6-luna")
  assert text2sql.describeLlmError(makeHttpError(401, "{}"), "openai/gpt-6-luna") == (
    "無法呼叫 OpenRouter（HTTP 401）：API key 錯誤，請確認 .env 的 OPENROUTER_API_KEY"
  )
  assert text2sql.describeLlmError(makeHttpError(402, "{}"), "openai/gpt-6-luna") == (
    "無法呼叫 OpenRouter（HTTP 402）：OpenRouter 餘額不足"
  )


def testDescribeLlmErrorTruncatesOtherHttpErrors(modelEnv):
  modelEnv(OPENROUTER_MODELS="openai/gpt-6-luna")
  prefix = "無法呼叫 OpenRouter（HTTP 502）："

  message = text2sql.describeLlmError(makeHttpError(502, "<html>" + "x" * 1000), "openai/gpt-6-luna")

  assert message.startswith(prefix + "<html>")
  assert len(message) == len(prefix) + 300


def testDescribeLlmErrorWithoutResponse(modelEnv):
  modelEnv(OPENROUTER_MODELS="openai/gpt-6-luna")
  error = requests.ConnectionError("連不上")
  assert text2sql.describeLlmError(error, "openai/gpt-6-luna") == "無法呼叫 OpenRouter：連不上"


def testDescribeLlmErrorKeepsOllamaHint(modelEnv):
  error = requests.ConnectionError("refused")
  assert text2sql.describeLlmError(error, "qwen2.5:3b") == (
    "無法呼叫 Ollama：refused\n\n請確認 Ollama 已啟動，且已下載 qwen2.5:3b。"
  )
```

`tests/test_text2sql.py` 開頭要加 `import requests`。

- [ ] **Step 2: 確認測試失敗**

Run: `python -m pytest tests/test_text2sql.py -q -k "Describe"`
Expected: FAIL，`AttributeError: module 'text2sql' has no attribute 'describeModel'`

- [ ] **Step 3: 在 `text2sql.py` 實作 `describeModel`、`describeLlmError`**

用 `getattr(error, "response", None)` 判斷有沒有 HTTP 回應。

- [ ] **Step 4: 確認測試通過**

Run: `python -m pytest -q`
Expected: 全部 PASS

- [ ] **Step 5: 修改 `app.py`**

- 第 69 行頁首說明列只留資料庫的部分，拿掉 `｜　text2sql 模型：…（Ollama）`，改由下拉選單顯示模型
- 「自然語言查詢」分頁在 `st.write(...)` 說明之後、範例按鈕之前加：
  ```python
  models = text2sql.listModels()
  selectedModel = st.selectbox(
    "模型", models, index=models.index(text2sql.getOllamaConfig()["model"]), format_func=text2sql.describeModel
  )
  ```
- `text2sql.answerQuestion(question.strip(), databaseUrl)` 改成多傳 `llm=text2sql.getLlm(selectedModel)`
- `except requests.RequestException` 裡的 `st.error(...)` 改成 `st.error(text2sql.describeLlmError(error, selectedModel))`

- [ ] **Step 6: 修改 `docker-compose.yml`**

app 的 `environment` 在 `OLLAMA_MODEL` 那一行後面加：

```yaml
      # 下面三個沒填也能啟動：沒有 key 時選單只會出現本機模型
      OLLAMA_MODELS: ${OLLAMA_MODELS:-}
      OPENROUTER_API_KEY: ${OPENROUTER_API_KEY:-}
      OPENROUTER_MODELS: ${OPENROUTER_MODELS:-}
```

- [ ] **Step 7: 更新 README**

- 「執行」一節：把 `- 想換模型：修改 .env 的 OLLAMA_MODEL，再執行 docker compose up -d` 改成說明下拉選單：預設模型是 `OLLAMA_MODEL`，選單裡的本機模型列在 `OLLAMA_MODELS`，改完執行 `docker compose up -d`
- 同一節新增一條：想用雲端模型時，在 `.env` 填 `OPENROUTER_API_KEY`（到 openrouter.ai 申請），執行 `docker compose up -d` 後，選單就會出現 `OPENROUTER_MODELS` 列出的模型；用雲端模型時，問題、資料表結構和資源名稱會送到 OpenRouter，再轉給模型的廠商
- 「結構」表 `text2sql.py` 那一列：把「呼叫 Ollama」改成「呼叫 Ollama 或 OpenRouter」

- [ ] **Step 8: 在 Docker 裡驗證**

Run:
```bash
docker compose config --quiet
docker compose up -d --build --wait
```
Expected: 兩個指令都 exit 0。打開 http://127.0.0.1:8501 的「自然語言查詢」：選單只有 `qwen2.5:3b（本機）`、`qwen3-vl:4b-instruct（本機）`，預設選 `.env` 的 `OLLAMA_MODEL`；兩個模型各問一次「明天有哪些行程？」，都顯示 SQL 和結果表格

- [ ] **Step 9: Commit**

```bash
git add text2sql.py tests/test_text2sql.py app.py docker-compose.yml README.md
git commit -m "app 的自然語言查詢加上模型下拉選單，雲端模型的錯誤訊息分開說明"
```

---

### Task 5: 評測支援雲端模型

**Files:**
- Modify: `evals/run.py:15`（`from functools import partial` 不再需要就移除）、`evals/run.py:106`（`--model` 說明）、`evals/run.py:113-120`（選 llm 的地方）
- Modify: `README.md`（「text2sql 評測」一節的 `--model` 說明）
- Test: `tests/test_evals.py`

**Interfaces:**
- Consumes: Task 3 的 `getProvider(model)`、`getOpenRouterConfig()`、`getLlm(model)`、`callOpenRouter`、fixture `modelEnv`

- [ ] **Step 1: 寫會失敗的測試**

```python
def testMainRejectsCloudModelWithoutApiKey(tmp_path, capsys, modelEnv):
  modelEnv(OPENROUTER_MODELS="openai/gpt-6-luna")

  with pytest.raises(SystemExit):
    evalRun.main(["--model", "openai/gpt-6-luna", "--filter", "b01", "--out", str(tmp_path)])

  assert "OPENROUTER_API_KEY" in capsys.readouterr().err
  assert list(tmp_path.iterdir()) == []


def testMainUsesOpenRouterForCloudModel(tmp_path, monkeypatch, modelEnv):
  modelEnv(OPENROUTER_MODELS="openai/gpt-6-luna", OPENROUTER_API_KEY="test-key")
  calledModels = []

  def fakeCallOpenRouter(messages, model, apiKey=None):
    calledModels.append(model)
    return "SELECT 1"

  monkeypatch.setattr(text2sql, "callOpenRouter", fakeCallOpenRouter)

  evalRun.main(["--model", "openai/gpt-6-luna", "--filter", "b01", "--out", str(tmp_path)])

  assert calledModels == ["openai/gpt-6-luna"]
  # 模型名稱的斜線不能變成子資料夾
  assert len(list(tmp_path.glob("openai-gpt-6-luna-dev-*.json"))) == 1
```

- [ ] **Step 2: 確認測試失敗**

Run: `python -m pytest tests/test_evals.py -q -k "CloudModel"`
Expected: 兩題都 FAIL。現在的程式會把 `openai/gpt-6-luna` 當成本機模型去呼叫 Ollama，得到 HTTP 錯誤或連線錯誤，而不是 `SystemExit`，也不會呼叫 `fakeCallOpenRouter`

- [ ] **Step 3: 修改 `evals/run.py` 的 `main`**

- `--model` 的 help 改成 `"模型名稱：本機 Ollama 模型，或 OPENROUTER_MODELS 裡的雲端模型"`
- 在 `--filter` 檢查之前：如果 `llm is None`、`text2sql.getProvider(args.model) == "openrouter"`，而且 `text2sql.getOpenRouterConfig()["apiKey"]` 是空的，就 `parser.error("請在 .env 設定 OPENROUTER_API_KEY 才能評測雲端模型")`
- `llm = llm or partial(text2sql.callOllama, model=args.model)` 改成 `llm = llm or text2sql.getLlm(args.model)`，並移除不再使用的 `partial` import

- [ ] **Step 4: 確認測試通過**

Run: `python -m pytest -q`
Expected: 全部 PASS

- [ ] **Step 5: 更新 README**

「text2sql 評測」一節的 `--model` 那一條改成：指定模型，可以是本機 Ollama 模型，或 `OPENROUTER_MODELS` 裡的雲端模型（需要 `OPENROUTER_API_KEY`，例如 `--model anthropic/claude-haiku-5.5`）；預設讀 `.env` 的 `OLLAMA_MODEL`

- [ ] **Step 6: Commit**

```bash
git add evals/run.py tests/test_evals.py README.md
git commit -m "評測的 --model 可以指定 OpenRouter 上的雲端模型"
```
