import os
import time

import httpx

# 沒設 num_ctx 時，預設值依 Ollama 版本而定，prompt 超過上限會被默默截掉、不報錯
ollamaNumCtx = 8192
localTimeout = 180
cloudTimeout = 60

# 每一家雲端供應商的設定都在這張表；新增供應商只要加一筆，呼叫、重試和錯誤處理共用同一份
cloudProviders = {
  "openrouter": {
    "label": "OpenRouter",
    "url": "https://openrouter.ai/api/v1/chat/completions",
    "apiKeyEnv": "OPENROUTER_API_KEY",
    "modelsEnv": "OPENROUTER_MODELS",
    "errorHints": {401: "API key 錯誤，請確認 .env 的 OPENROUTER_API_KEY", 402: "OpenRouter 餘額不足"},
  },
  # key 填錯時 Google 回 400，原文就寫得很清楚，所以只補帳單和額度這兩種原文看不出原因的狀況
  "google": {
    "label": "Google",
    "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    "apiKeyEnv": "GOOGLE_AI_API_KEY",
    "modelsEnv": "GOOGLE_AI_MODELS",
    "errorHints": {
      403: "請確認 AI Studio 已綁定帳單，而且 key 屬於有 credits 的專案",
      429: "額度用完或呼叫太頻繁，請到 AI Studio 查看用量",
    },
  },
}
cloudRetryStatuses = {429, 500, 502, 503, 504}
cloudRetryWaits = [2, 4]


class LlmUnavailableError(Exception):
  def __init__(self, message: str):
    super().__init__(message)
    self.message = message


def parseModelList(text: str | None) -> list[str]:
  return [name.strip() for name in (text or "").split(",") if name.strip()]


def getOllamaConfig() -> dict:
  return {
    "url": os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/"),
    "model": os.getenv("OLLAMA_MODEL", "qwen2.5:3b"),
  }


def getLocalModels() -> list[str]:
  defaultModel = getOllamaConfig()["model"]
  return list(dict.fromkeys([defaultModel, *parseModelList(os.getenv("LOCAL_MODELS"))]))


def getCloudConfig(provider: str) -> dict:
  config = cloudProviders[provider]
  return {"apiKey": os.getenv(config["apiKeyEnv"], "").strip(), "models": parseModelList(os.getenv(config["modelsEnv"]))}


def listModels() -> list[dict]:
  localModels = getLocalModels()
  result = [{"id": model, "label": f"{model}（本機）", "remote": False} for model in localModels]
  seen = set(localModels)
  for provider, config in cloudProviders.items():
    cloud = getCloudConfig(provider)
    # 沒有 key 就選不到這一家的模型，免得使用者選了之後才看到 401
    if not cloud["apiKey"]:
      continue
    for model in cloud["models"]:
      if model not in seen:
        seen.add(model)
        result.append({"id": model, "label": f"{model}（{config['label']}）", "remote": True})
  return result


def getProvider(model: str) -> str:
  # 本機優先，和 listModels 的順序一致：同一個 id 同時出現在本機與雲端清單時，走本機
  if model in getLocalModels():
    return "ollama"
  # 只看清單、不看名稱有沒有斜線：Ollama 的模型名稱也可能是 hf.co/... 這種格式
  for provider in cloudProviders:
    cloud = getCloudConfig(provider)
    if cloud["apiKey"] and model in cloud["models"]:
      return provider
  return "ollama"


def describeError(error: Exception, model: str, provider: str) -> str:
  if provider == "ollama":
    return f"無法呼叫 Ollama：{error}。請確認 Ollama 已啟動，且已下載 {model}。"
  config = cloudProviders[provider]
  apiKey = getCloudConfig(provider)["apiKey"]
  response = getattr(error, "response", None)
  if response is None:
    text = f"無法呼叫 {config['label']}：{error}"
  else:
    # 閘道錯誤常回整頁 HTML，只留開頭，畫面才不會被塞滿
    raw = response.text
    # 供應商可能把送出的 key 回顯在錯誤內容裡，遮掉後才能顯示到畫面上；命中 errorHints 時是我們自己寫的文字，不用處理
    if apiKey:
      raw = raw.replace(apiKey, "***")
    # 先遮 key 再截斷：key 若剛好跨過 300 字的邊界，先截斷會留下半截 key
    raw = raw[:300]
    detail = config["errorHints"].get(response.status_code, raw)
    text = f"無法呼叫 {config['label']}（HTTP {response.status_code}）：{detail}"
  return text


def callOllama(client: httpx.Client, model: str, messages: list[dict]) -> str:
  response = client.post(
    f"{getOllamaConfig()['url']}/api/chat",
    json={
      "model": model, "messages": messages, "stream": False,
      # 溫度設 0：同一個問題盡量產生同一句 SQL，結果比較穩定也比較好除錯
      "options": {"temperature": 0, "num_ctx": ollamaNumCtx},
    },
    timeout=localTimeout,
  )
  response.raise_for_status()
  return response.json()["message"]["content"]


def callCloud(client: httpx.Client, provider: str, model: str, messages: list[dict], sleep) -> str:
  config = cloudProviders[provider]
  # 429 和 5xx 多半是暫時的，等一下再試；401、402 這類重試也沒用，直接往下報錯
  for waitSeconds in [*cloudRetryWaits, None]:
    response = client.post(
      config["url"],
      headers={"Authorization": f"Bearer {getCloudConfig(provider)['apiKey']}"},
      json={"model": model, "messages": messages, "temperature": 0},
      timeout=cloudTimeout,
    )
    if response.status_code not in cloudRetryStatuses or waitSeconds is None:
      break
    sleep(waitSeconds)
  response.raise_for_status()
  payload = response.json()
  choices = payload.get("choices") if isinstance(payload, dict) else None
  if not choices:
    raise LlmUnavailableError(f"{config['label']} 的回應沒有 choices")
  # 推理模型只回傳思考內容、或被安全機制擋下時 content 是 null，當成沒產生 SQL 交給後面處理
  return (choices[0].get("message") or {}).get("content") or ""


def callModel(model: str, messages: list[dict], client: httpx.Client | None = None, sleep=time.sleep) -> str:
  provider = getProvider(model)
  label = "Ollama" if provider == "ollama" else cloudProviders[provider]["label"]
  ownClient = client is None
  client = client or httpx.Client()
  try:
    if provider == "ollama":
      return callOllama(client, model, messages)
    return callCloud(client, provider, model, messages, sleep)
  except httpx.HTTPError as error:
    raise LlmUnavailableError(describeError(error, model, provider))
  # 2xx 但內容不是預期的 JSON 格式（例如代理回 HTML、缺 message 欄位）；只回格式錯誤，不把原始回應帶到畫面上
  except (ValueError, KeyError, TypeError, AttributeError):
    raise LlmUnavailableError(f"{label} 的回應格式不正確")
  finally:
    if ownClient:
      client.close()
