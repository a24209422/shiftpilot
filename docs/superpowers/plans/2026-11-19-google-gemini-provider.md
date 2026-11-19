# 直連 Google Gemini API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 OpenRouter 專用的雲端呼叫改成「依供應商表呼叫」的通用版，再把 Google 的 Gemini API 加進表裡，讓選單與評測可以選 Gemini。

**Architecture:** `text2sql.py` 新增模組常數 `cloudProviders`（每家的名稱、網址、key 與模型清單的環境變數、錯誤提示），`callCloudModel(messages, provider, model)` 取代 `callOpenRouter`，`getCloudConfig(provider)` 取代 `getOpenRouterConfig`。`listModels`、`getProvider`、`getLlm`、`describeModel`、`describeLlmError` 改成走表。Task 1 是純重構（只有 OpenRouter，行為不變），Task 2 在表裡加 Google。`app.py` 不用改。

**Tech Stack:** Python 3.13、Streamlit、requests、pytest、Docker

**Spec:** `docs/superpowers/specs/2026-11-19-google-gemini-provider-design.md`

## Global Constraints

- 縮排 2 個空白；camelCase；註解用正體中文，只寫「為什麼」
- 不新增套件；`callOllama`、`getOllamaConfig` 一行都不改
- OpenRouter 的行為不變：網址 `https://openrouter.ai/api/v1/chat/completions`、header 只有 `Authorization: Bearer <key>`、body 只有 `model`/`messages`/`temperature: 0`、`timeout=60`、重試狀態 `{429, 500, 502, 503, 504}` 等 `[2, 4]` 秒、錯誤文字照舊（例如 `無法呼叫 OpenRouter（HTTP 401）：API key 錯誤，請確認 .env 的 OPENROUTER_API_KEY`）
- Google：網址 `https://generativelanguage.googleapis.com/v1beta/openai/chat/completions`，其餘 header、body、timeout、重試都跟 OpenRouter 相同
- 環境變數：`GOOGLE_AI_API_KEY`（`.env.example` 留空）、`GOOGLE_AI_MODELS=gemini-3.5-flash-lite,gemini-3.8-flash`
- Google 錯誤文字：
  - 403：`無法呼叫 Google（HTTP 403）：請確認 AI Studio 已綁定帳單，而且 key 屬於有 credits 的專案`
  - 429：`無法呼叫 Google（HTTP 429）：額度用完或呼叫太頻繁，請到 AI Studio 查看用量`
  - 其他狀態：`無法呼叫 Google（HTTP {status}）：{response.text[:300]}`；沒有 response：`無法呼叫 Google：{error}`
- 所有雲端模型在選單都標 `（雲端）`
- 測試絕對不能真的呼叫雲端 API；`modelEnv` 要把所有雲端相關變數設成空字串（不是刪掉，否則 `evals.run.main` 的 `load_dotenv` 會載回真的 key）
- commit 訊息用正體中文，結尾加 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`；不 push

## Review Focus

1. 只填 Google 的 key、沒填 OpenRouter 的 → 選單只多出 Google 的模型（Task 2：`testListModelsAddsGoogleModelsWithOnlyGoogleKey`）
2. Google key 錯誤時 Google 回 400 → 顯示原文（含 `API key not valid`），不是誤導的提示（Task 2：`testDescribeLlmErrorShowsGoogleBodyForInvalidKey`）
3. 評測指定 Gemini 卻沒填 Google 的 key → 錯誤訊息指出 `GOOGLE_AI_API_KEY`，不是 OpenRouter 的變數（Task 2：`testMainRejectsGoogleModelWithoutApiKey`）
4. 使用者 `.env` 填了 Google key 之後跑測試 → 測試仍拿不到真的 key（Task 2：`testModelEnvStopsDotenvFromRestoringApiKey` 參數化涵蓋兩家）
5. 同一個名稱同時列在兩家清單 → 以 OpenRouter 為準，選單只出現一次（Task 2：`testModelInBothCloudListsGoesToOpenRouterOnce`）

---

### Task 1: 雲端呼叫改成依供應商表（純重構）

**Files:**
- Modify: `text2sql.py`（`openRouterUrl` 到 `describeLlmError` 這一段）
- Modify: `evals/run.py`（`main` 裡的 key 檢查）
- Test: `tests/test_text2sql.py`、`tests/test_evals.py`

**Interfaces:**
- Produces:
  - `cloudProviders: dict[str, dict]`，這個 Task 只有 `"openrouter"`：`{"label": "OpenRouter", "url": "https://openrouter.ai/api/v1/chat/completions", "apiKeyEnv": "OPENROUTER_API_KEY", "modelsEnv": "OPENROUTER_MODELS", "errorHints": {401: "API key 錯誤，請確認 .env 的 OPENROUTER_API_KEY", 402: "OpenRouter 餘額不足"}}`
  - `cloudRetryStatuses = {429, 500, 502, 503, 504}`、`cloudRetryWaits = [2, 4]`
  - `class CloudResponseError(requests.RequestException)`：訊息 `f"{label} 的回應沒有 choices"`
  - `getCloudConfig(provider: str) -> dict`：`{"apiKey": str（已 strip）, "models": list[str]}`
  - `callCloudModel(messages: list[dict], provider: str, model: str, apiKey: str | None = None) -> str`
  - `getProvider(model: str) -> str`：依 `cloudProviders` 的順序，第一個清單裡有這個模型的供應商；都沒有就是 `"ollama"`
  - `getLlm(model)`：雲端回 `partial(callCloudModel, provider=..., model=...)`，本機回 `partial(callOllama, model=...)`
  - `listModels()`：本機模型，接著依表的順序，每一家有 key 時接上它的模型，去除重複
  - `describeModel`、`describeLlmError` 簽名不變，名稱與提示從表裡拿
  - 移除：`openRouterUrl`、`getOpenRouterConfig`、`callOpenRouter`、`OpenRouterResponseError`、`openRouterRetryStatuses`、`openRouterRetryWaits`

- [ ] **Step 1: 開分支並 commit 設計文件與計畫**

```bash
git checkout -b feat/google-gemini
git add docs/superpowers/specs/2026-11-19-google-gemini-provider-design.md docs/superpowers/plans/2026-11-19-google-gemini-provider.md
git commit -m "新增直連 Google Gemini API 的設計文件與實作計畫"
```

- [ ] **Step 2: 把測試改成新的名稱（斷言的值都不變）**

`tests/test_text2sql.py`：
- `text2sql.callOpenRouter(messages, model=X)` 全部改成 `text2sql.callCloudModel(messages, provider="openrouter", model=X)`（`testCallOpenRouterSendsChatRequest`、`...TreatsNullContentAsEmpty`、`...RetriesRateLimitThenSucceeds`、`...GivesUpAfterThreeAttempts`、`...DoesNotRetryAuthError`、`...RaisesRequestErrorWhenChoicesMissing`）
- `testGetLlmRoutesByProvider`：`assert cloudLlm.func is text2sql.callCloudModel`、`assert cloudLlm.keywords == {"provider": "openrouter", "model": "openai/gpt-6-luna"}`

`tests/test_evals.py`：
- `testMainUsesOpenRouterForCloudModel`：假函式改成 `def fakeCallCloudModel(messages, provider, model, apiKey=None)`，記錄 `(provider, model)`，`monkeypatch.setattr(text2sql, "callCloudModel", fakeCallCloudModel)`，斷言 `calledModels == [("openrouter", "openai/gpt-6-luna")]`
- `testModelEnvStopsDotenvFromRestoringApiKey`：改成 `text2sql.getCloudConfig("openrouter")["apiKey"] == ""`

- [ ] **Step 3: 確認測試失敗**

Run: `python -m pytest tests/test_text2sql.py tests/test_evals.py -q -k "OpenRouter or GetLlm or ModelEnvStops or CloudModel"`
Expected: FAIL，`AttributeError: module 'text2sql' has no attribute 'callCloudModel'`（或 `getCloudConfig`）

- [ ] **Step 4: 在 `text2sql.py` 實作 Interfaces 列出的常數與函式，移除舊名稱**

- `describeLlmError`：`getProvider` 是 `"ollama"` 時維持原本的 Ollama 訊息；雲端時用 `cloudProviders[provider]["label"]` 和 `["errorHints"]` 組出跟現在一模一樣的文字
- `evals/run.py`：key 檢查改成 `provider = text2sql.getProvider(args.model)`；`llm is None`、`provider != "ollama"`、而且 `text2sql.getCloudConfig(provider)["apiKey"]` 是空的時，`parser.error(f"請在 .env 設定 {text2sql.cloudProviders[provider]['apiKeyEnv']} 才能評測雲端模型")`

- [ ] **Step 5: 確認全部測試通過**

Run: `python -m pytest -q`
Expected: 全部 PASS（跟重構前一樣是 163 個）

- [ ] **Step 6: Commit**

```bash
git add text2sql.py evals/run.py tests/test_text2sql.py tests/test_evals.py
git commit -m "雲端模型呼叫改成依供應商表，為加入其他供應商做準備"
```

---

### Task 2: 加入 Google 的 Gemini API

**Files:**
- Modify: `text2sql.py`（`cloudProviders` 加 `"google"`）
- Modify: `tests/conftest.py`（`emptiedModelEnvNames`）
- Modify: `.env.example`、`.env`（只在結尾補上缺少的行，不 commit）、`docker-compose.yml`、`README.md`
- Test: `tests/test_text2sql.py`、`tests/test_evals.py`

**Interfaces:**
- Consumes: Task 1 的 `cloudProviders`、`getCloudConfig`、`callCloudModel`、`getProvider`、`getLlm`、`listModels`、`describeModel`、`describeLlmError`
- Produces: `cloudProviders["google"] = {"label": "Google", "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", "apiKeyEnv": "GOOGLE_AI_API_KEY", "modelsEnv": "GOOGLE_AI_MODELS", "errorHints": {403: "請確認 AI Studio 已綁定帳單，而且 key 屬於有 credits 的專案", 429: "額度用完或呼叫太頻繁，請到 AI Studio 查看用量"}}`，排在 `"openrouter"` 之後

- [ ] **Step 1: `tests/conftest.py` 的 `emptiedModelEnvNames` 加上 `"GOOGLE_AI_API_KEY"`、`"GOOGLE_AI_MODELS"`**

- [ ] **Step 2: 在 `tests/test_text2sql.py` 寫會失敗的測試**

```python
googleModels = "gemini-3.5-flash-lite,gemini-3.8-flash"


def testListModelsAddsGoogleModelsWithOnlyGoogleKey(modelEnv):
  modelEnv(OLLAMA_MODEL="qwen2.5:3b", LOCAL_MODELS="qwen2.5:3b", OPENROUTER_MODELS=cloudModels,
           GOOGLE_AI_API_KEY="google-key", GOOGLE_AI_MODELS=googleModels)
  assert text2sql.listModels() == ["qwen2.5:3b", "gemini-3.5-flash-lite", "gemini-3.8-flash"]


def testModelInBothCloudListsGoesToOpenRouterOnce(modelEnv):
  modelEnv(OLLAMA_MODEL="qwen2.5:3b", LOCAL_MODELS="qwen2.5:3b",
           OPENROUTER_API_KEY="openrouter-key", OPENROUTER_MODELS="gemini-3.5-flash-lite",
           GOOGLE_AI_API_KEY="google-key", GOOGLE_AI_MODELS="gemini-3.5-flash-lite")
  assert text2sql.listModels() == ["qwen2.5:3b", "gemini-3.5-flash-lite"]
  assert text2sql.getProvider("gemini-3.5-flash-lite") == "openrouter"


def testGetLlmRoutesGoogleModels(modelEnv):
  modelEnv(GOOGLE_AI_MODELS=googleModels)
  googleLlm = text2sql.getLlm("gemini-3.5-flash-lite")
  assert googleLlm.func is text2sql.callCloudModel
  assert googleLlm.keywords == {"provider": "google", "model": "gemini-3.5-flash-lite"}


def testCallCloudModelSendsGoogleRequest(monkeypatch, modelEnv):
  modelEnv(GOOGLE_AI_API_KEY="google-key")
  fakePost = makeFakePost("```sql\nSELECT 1\n```")
  monkeypatch.setattr(text2sql.requests, "post", fakePost)
  messages = [{"role": "user", "content": "問題"}]

  reply = text2sql.callCloudModel(messages, provider="google", model="gemini-3.5-flash-lite")

  call = fakePost.calls[0]
  assert reply == "```sql\nSELECT 1\n```"
  assert call["url"] == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
  assert call["headers"] == {"Authorization": "Bearer google-key"}
  assert call["json"] == {"model": "gemini-3.5-flash-lite", "messages": messages, "temperature": 0}
  assert call["timeout"] == 60


def testDescribeModelMarksGoogleAsCloud(modelEnv):
  modelEnv(GOOGLE_AI_MODELS=googleModels)
  assert text2sql.describeModel("gemini-3.5-flash-lite") == "gemini-3.5-flash-lite（雲端）"


def testDescribeLlmErrorExplainsGoogleBillingAndQuota(modelEnv):
  modelEnv(GOOGLE_AI_MODELS=googleModels)
  assert text2sql.describeLlmError(makeHttpError(403, "{}"), "gemini-3.5-flash-lite") == (
    "無法呼叫 Google（HTTP 403）：請確認 AI Studio 已綁定帳單，而且 key 屬於有 credits 的專案"
  )
  assert text2sql.describeLlmError(makeHttpError(429, "{}"), "gemini-3.5-flash-lite") == (
    "無法呼叫 Google（HTTP 429）：額度用完或呼叫太頻繁，請到 AI Studio 查看用量"
  )


def testDescribeLlmErrorShowsGoogleBodyForInvalidKey(modelEnv):
  modelEnv(GOOGLE_AI_MODELS=googleModels)
  body = '{"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.", "status": "INVALID_ARGUMENT"}}'

  message = text2sql.describeLlmError(makeHttpError(400, body), "gemini-3.5-flash-lite")

  assert message.startswith("無法呼叫 Google（HTTP 400）：")
  assert "API key not valid" in message


def testDescribeLlmErrorWithoutResponseNamesGoogle(modelEnv):
  modelEnv(GOOGLE_AI_MODELS=googleModels)
  error = requests.ConnectionError("連不上")
  assert text2sql.describeLlmError(error, "gemini-3.5-flash-lite") == "無法呼叫 Google：連不上"
```

- [ ] **Step 3: 在 `tests/test_evals.py` 寫會失敗的測試**

```python
def testMainRejectsGoogleModelWithoutApiKey(tmp_path, capsys, modelEnv):
  modelEnv(GOOGLE_AI_MODELS="gemini-3.5-flash-lite")

  with pytest.raises(SystemExit):
    evalRun.main(["--model", "gemini-3.5-flash-lite", "--filter", "b01", "--out", str(tmp_path)])

  assert "GOOGLE_AI_API_KEY" in capsys.readouterr().err
  assert list(tmp_path.iterdir()) == []
```

`testModelEnvStopsDotenvFromRestoringApiKey` 改成參數化：

```python
@pytest.mark.parametrize("provider, apiKeyEnv", [("openrouter", "OPENROUTER_API_KEY"), ("google", "GOOGLE_AI_API_KEY")])
def testModelEnvStopsDotenvFromRestoringApiKey(modelEnv, provider, apiKeyEnv):
  # evalRun.main 一開始會執行 load_dotenv()；使用者的 .env 填了 key 之後，測試不能因此拿到真的 key
  load_dotenv(stream=io.StringIO(f"{apiKeyEnv}=real-key"))
  assert text2sql.getCloudConfig(provider)["apiKey"] == ""
```

- [ ] **Step 4: 確認測試失敗**

Run: `python -m pytest tests/test_text2sql.py tests/test_evals.py -q -k "Google or ModelEnvStops"`
Expected: Google 相關的測試 FAIL（`KeyError: 'google'`，或模型被當成本機模型；`testMainRejectsGoogleModelWithoutApiKey` 會把 Gemini 當本機模型去叫 Ollama、記成連線錯誤後跑完，沒有 `SystemExit`）。兩個測試在實作前就會 PASS：`ModelEnvStops[openrouter]`，以及 `testModelInBothCloudListsGoesToOpenRouterOnce`（表裡還沒有 Google，它是防止加入 Google 後順序或去重出錯的護欄）

- [ ] **Step 5: 在 `cloudProviders` 加入 Interfaces 列出的 `"google"`**

- [ ] **Step 6: 確認全部測試通過**

Run: `python -m pytest -q`
Expected: 全部 PASS

- [ ] **Step 7: 更新設定檔**

`.env.example` 在 `OPENROUTER_MODELS=...` 後面加：

```
# Google 的 Gemini API（到 Google AI Studio 建立 key；Google AI Pro 每月附的 Cloud credits 可以拿來付費）
# 不用官方慣用的 GEMINI_API_KEY：Gemini CLI 等工具也讀這個名字，系統層級設了會蓋過這裡
GOOGLE_AI_API_KEY=
GOOGLE_AI_MODELS=gemini-3.5-flash-lite,gemini-3.8-flash
```

`.env`：用 `grep -c "^GOOGLE_AI_API_KEY=\|^GOOGLE_AI_MODELS=" .env` 檢查（不印出內容），只在結尾補上缺少的行。

`docker-compose.yml` app 的 `environment` 在 `OPENROUTER_MODELS` 後面加 `GOOGLE_AI_API_KEY: ${GOOGLE_AI_API_KEY:-}`、`GOOGLE_AI_MODELS: ${GOOGLE_AI_MODELS:-}`，上方註解的「下面三個」改成「下面幾個」。

- [ ] **Step 8: 更新 README**

- 「執行」一節「用雲端模型」那條後面新增一條「用 Google 的 Gemini」：到 Google AI Studio 領取 Google AI Pro 附的 Cloud credits、綁定帳單（第三方資料說可能要先預付 US$5，以 AI Studio 畫面為準）、建立 API key，填進 `.env` 的 `GOOGLE_AI_API_KEY`，執行 `docker compose up -d` 後選單會出現 `GOOGLE_AI_MODELS` 的模型；資料會送到 Google
- 「text2sql 評測」一節的 `--model` 說明加上 `GOOGLE_AI_MODELS` 的模型（需要 `GOOGLE_AI_API_KEY`）
- 「結構」表 `text2sql.py` 那一列：「呼叫 Ollama 或 OpenRouter」改成「呼叫 Ollama、OpenRouter 或 Google」

- [ ] **Step 9: 在 Docker 裡驗證**

Run:
```bash
docker compose config --quiet
docker compose up -d --build --wait
docker compose exec -T app python -c "import text2sql; print(text2sql.listModels())"
```
Expected: 都 exit 0；沒有任何 key 時印出 `['qwen2.5:3b', 'qwen3-vl:4b-instruct']`

- [ ] **Step 10: Commit**

```bash
git add text2sql.py tests/conftest.py tests/test_text2sql.py tests/test_evals.py .env.example docker-compose.yml README.md
git commit -m "加入直連 Google 的 Gemini API，可以在選單和評測選 Gemini"
```
