"""自然語言 → PostgreSQL 查詢。只產生並執行唯讀的 SELECT。"""
import os
import re
import time
from datetime import datetime, timedelta
from functools import partial

import psycopg
import requests

import db

weekdayNames = ["一", "二", "三", "四", "五", "六", "日"]
# WITH 開頭的查詢可以在子句裡夾帶寫入語句，只檢查開頭是不是 SELECT / WITH 不夠
forbiddenPattern = re.compile(
  r"\b(insert|update|delete|merge|truncate|drop|alter|create|grant|revoke|copy|vacuum|reindex|lock)\b",
  re.IGNORECASE,
)


class UnsafeSqlError(ValueError):
  pass


def getOllamaConfig():
  return {
    "url": os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/"),
    "model": os.getenv("OLLAMA_MODEL", "qwen2.5:3b"),
  }


# 沒設 num_ctx 時，預設值依 Ollama 版本而定，prompt 超過上限會被默默截掉、不報錯。
# 這個值會影響分數，所以寫死在程式裡而不是放 .env，才不會因為環境不同讓分數無法比較
ollamaNumCtx = 8192


def callOllama(messages, model=None, url=None):
  config = getOllamaConfig()
  response = requests.post(
    f"{url or config['url']}/api/chat",
    json={
      "model": model or config["model"],
      "messages": messages,
      "stream": False,
      # 溫度設 0：同一個問題盡量產生同一句 SQL，結果比較穩定也比較好除錯
      "options": {"temperature": 0, "num_ctx": ollamaNumCtx},
    },
    timeout=180,
  )
  response.raise_for_status()
  return response.json()["message"]["content"]


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


def parseModelList(text):
  return [name.strip() for name in (text or "").split(",") if name.strip()]


def getCloudConfig(provider):
  config = cloudProviders[provider]
  return {
    "apiKey": os.getenv(config["apiKeyEnv"], "").strip(),
    "models": parseModelList(os.getenv(config["modelsEnv"])),
  }


def listModels():
  defaultModel = getOllamaConfig()["model"]
  localModels = parseModelList(os.getenv("LOCAL_MODELS"))
  if defaultModel not in localModels:
    localModels.insert(0, defaultModel)
  cloudModels = []
  for provider in cloudProviders:
    config = getCloudConfig(provider)
    # 沒有 key 就選不到這一家的模型，免得使用者選了之後才看到 401
    if config["apiKey"]:
      cloudModels += config["models"]
  return list(dict.fromkeys(localModels + cloudModels))


def getProvider(model):
  # 只看清單、不看名稱有沒有斜線：Ollama 的模型名稱也可能是 hf.co/... 這種格式
  for provider in cloudProviders:
    if model in getCloudConfig(provider)["models"]:
      return provider
  return "ollama"


def getLlm(model):
  provider = getProvider(model)
  if provider == "ollama":
    return partial(callOllama, model=model)
  return partial(callCloudModel, provider=provider, model=model)


class CloudResponseError(requests.RequestException):
  pass


def callCloudModel(messages, provider, model, apiKey=None):
  config = cloudProviders[provider]
  # 429 和 5xx 多半是暫時的，等一下再試；401、402 這類重試也沒用，直接往下報錯。最後一次失敗後不再等
  for waitSeconds in [*cloudRetryWaits, None]:
    response = requests.post(
      config["url"],
      headers={"Authorization": f"Bearer {apiKey or getCloudConfig(provider)['apiKey']}"},
      json={"model": model, "messages": messages, "temperature": 0},
      timeout=60,
    )
    if response.status_code not in cloudRetryStatuses or waitSeconds is None:
      break
    time.sleep(waitSeconds)
  response.raise_for_status()
  payload = response.json()
  choices = payload.get("choices") if isinstance(payload, dict) else None
  if not choices:
    # 回應不是物件、沒有 choices 或 choices 是空的（例如只有 error），改成 RequestException，
    # app 和評測才會當成連線錯誤，而不是整個當掉、讓評測丟掉前面已經跑完的題目
    raise CloudResponseError(f"{config['label']} 的回應沒有 choices", response=response)
  # 推理模型只回傳思考內容、或被安全機制擋下時，content 是 null、整個 message 不存在，
  # 都當成模型沒產生 SQL 交給後面處理：它有回應，只是沒給答案，評測要算答錯
  return (choices[0].get("message") or {}).get("content") or ""


def describeModel(model):
  return f"{model}（{'本機' if getProvider(model) == 'ollama' else '雲端'}）"


def describeLlmError(error, model):
  provider = getProvider(model)
  if provider == "ollama":
    return f"無法呼叫 Ollama：{error}\n\n請確認 Ollama 已啟動，且已下載 {model}。"
  config = cloudProviders[provider]
  response = getattr(error, "response", None)
  if response is None:
    return f"無法呼叫 {config['label']}：{error}"
  # 閘道錯誤常回整頁 HTML，只留開頭，畫面才不會被塞滿
  detail = config["errorHints"].get(response.status_code, response.text[:300])
  return f"無法呼叫 {config['label']}（HTTP {response.status_code}）：{detail}"


def extractSql(text):
  # qwen3 這類推理模型會先輸出 <think> 區塊
  text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
  fenced = re.search(r"```(?:sql)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
  if fenced:
    text = fenced.group(1)
  else:
    # 小模型常不照格式，在 SQL 前面加說明文字，所以從第一個 SELECT / WITH 開始取
    start = re.search(r"\b(select|with)\b", text, flags=re.IGNORECASE)
    if start:
      text = text[start.start():]
  # 分號後面通常是模型補的解釋；只取第一句也順便擋掉多語句
  return text.split(";")[0].strip()


def validateSql(sql):
  if not sql:
    raise UnsafeSqlError("模型沒有產生 SQL")
  if not re.match(r"^\s*(select|with)\b", sql, re.IGNORECASE):
    raise UnsafeSqlError("只允許 SELECT 查詢")
  if ";" in sql:
    raise UnsafeSqlError("只允許單一 SQL 語句")
  if forbiddenPattern.search(sql):
    raise UnsafeSqlError("SQL 含有不允許的關鍵字")


def buildDateReference(now):
  # 小模型很不會算「下週三」是哪天，直接把兩週的日期表給它查
  today = now.date()
  monday = today - timedelta(days=today.weekday())
  lines = [
    f"今天是 {today} 星期{weekdayNames[today.weekday()]}，現在時間 {now.strftime('%H:%M')}。一週從星期一開始。",
    f"本週：{monday} ～ {monday + timedelta(days=6)}",
    f"下週：{monday + timedelta(days=7)} ～ {monday + timedelta(days=13)}",
    f"上週：{monday - timedelta(days=7)} ～ {monday - timedelta(days=1)}",
    f"這兩週（本週＋下週）：{monday} ～ {monday + timedelta(days=13)}",
  ]
  relativeNames = {-1: "昨天", 0: "今天", 1: "明天", 2: "後天"}
  for offset in range(-1, 14):
    day = today + timedelta(days=offset)
    label = f"（{relativeNames[offset]}）" if offset in relativeNames else ""
    lines.append(f"{day} 星期{weekdayNames[day.weekday()]}{label}")
  return "\n".join(lines)


def buildMessages(question, schemaText, vocabulary, now):
  today = now.date()
  tomorrow = today + timedelta(days=1)
  nextMonday = today - timedelta(days=today.weekday()) + timedelta(days=7)
  nextSunday = nextMonday + timedelta(days=6)
  nowText = now.strftime("%Y-%m-%d %H:%M")

  systemPrompt = f"""你是 PostgreSQL 專家，負責把使用者的中文問題轉成一句 PostgreSQL 查詢。

規則：
1. 只輸出一句 SELECT（或 WITH ... SELECT），放在 ```sql 區塊裡，不要任何解釋。
2. 只能使用下方 schema 裡的資料表與欄位。排程在 events，資源在 resources，兩者透過 event_resources 對應；同時用到排程和資源時，JOIN 這三張表。
3. 時間欄位是 timestamp。取日期用 start_at::date，取時間用 start_at::time，可以直接跟 'YYYY-MM-DD'、'HH:MM' 格式的字串比較。
4. 不要用 CURRENT_DATE 或 now()，日期一律以下方「日期參考」為準。
5. 比對名稱或標題時用 LIKE '%關鍵字%'，因為使用者常只講部分名字。
6. 列出排程時帶出資源名稱（resources.name），並依 start_at 排序，讓結果看得懂。
7. 使用者提到排程名稱（例如「晚班」「週會」）時，用 title LIKE 比對，不要自己推算時段，也不要猜它屬於哪個 category。
8. 「人」「每個人」「員工」「誰」指 resources.type = 'person'；「會議室」指 'room'；「設備」指 'equipment'。
9. JOIN event_resources 之後，一筆排程有幾個資源就有幾列。計算「幾筆排程」「幾場會議」時用 COUNT(DISTINCT events.id)，不要用 COUNT(*)。
10. 這是 PostgreSQL，不要用 julianday()、strftime() 這類 SQLite 函式。時長用 EXTRACT(EPOCH FROM end_at - start_at) / 3600 換算成小時。
11. 現在時間是 '{nowText}'。問「下一個」「接下來」的排程時用 start_at > '{nowText}'。問某個時間點「正在進行」的排程時用 start_at <= 該時間點 AND end_at > 該時間點。
12. 同一筆排程的每個資源在 event_resources 裡都有相同的 event_id。要找兩個資源一起參與的排程（例如某人在某間會議室開的會），用 events.id IN (SELECT event_resources.event_id FROM event_resources JOIN resources ON resources.id = event_resources.resource_id WHERE ...) 子查詢。

## Schema
{schemaText}

## 目前資料中的值
- events.category：{', '.join(vocabulary['categories']) or '（尚無）'}
- resources.type：{', '.join(vocabulary['resourceTypes']) or '（尚無）'}
- resources.name：{', '.join(vocabulary['resourceNames']) or '（尚無）'}

## 日期參考
{buildDateReference(now)}
"""
  # few-shot 範例的日期跟著今天變，模型才學得到「明天」「下週」要換成實際日期
  fewShots = [
    (
      "明天小明有什麼行程？",
      "SELECT resources.name, events.title, events.start_at, events.end_at\n"
      "FROM events\n"
      "JOIN event_resources ON event_resources.event_id = events.id\n"
      "JOIN resources ON resources.id = event_resources.resource_id\n"
      f"WHERE resources.name LIKE '%小明%' AND events.start_at::date = '{tomorrow}'\n"
      "ORDER BY events.start_at",
    ),
    (
      "下週總共有幾場會議？",
      "SELECT COUNT(DISTINCT events.id) AS meeting_count\n"
      "FROM events\n"
      f"WHERE events.category = 'meeting' AND events.start_at::date BETWEEN '{nextMonday}' AND '{nextSunday}'",
    ),
    # 前兩個範例都有日期條件，小模型會照抄，連沒問日期的題目也加上日期範圍；這個範例刻意不帶日期
    (
      "李小華和陳大文一起參加過哪些排程？",
      "SELECT events.title, events.start_at, events.end_at\n"
      "FROM events\n"
      "JOIN event_resources ON event_resources.event_id = events.id\n"
      "JOIN resources ON resources.id = event_resources.resource_id\n"
      "WHERE resources.name LIKE '%李小華%'\n"
      "  AND events.id IN (\n"
      "    SELECT event_resources.event_id FROM event_resources\n"
      "    JOIN resources ON resources.id = event_resources.resource_id\n"
      "    WHERE resources.name LIKE '%陳大文%')\n"
      "ORDER BY events.start_at",
    ),
  ]
  messages = [{"role": "system", "content": systemPrompt}]
  for exampleQuestion, exampleSql in fewShots:
    messages.append({"role": "user", "content": exampleQuestion})
    messages.append({"role": "assistant", "content": f"```sql\n{exampleSql}\n```"})
  messages.append({"role": "user", "content": question})
  return messages


def answerQuestion(question, databaseUrl, now=None, llm=None, maxRetries=1):
  now = now or datetime.now()
  llm = llm or callOllama
  messages = buildMessages(question, db.getLlmSchemaText(), db.getVocabulary(databaseUrl), now)
  sql, lastError = "", None
  for attempt in range(1, maxRetries + 2):
    rawReply = llm(messages)
    sql = extractSql(rawReply)
    try:
      validateSql(sql)
      columns, rows = db.runReadOnlyQuery(databaseUrl, sql)
      return {"sql": sql, "columns": columns, "rows": rows, "error": None, "attempts": attempt}
    except (UnsafeSqlError, psycopg.Error) as error:
      lastError = error
      # 把錯誤訊息回饋給模型重試：小模型常拼錯欄位名稱，給它看錯誤通常一次就能修好
      messages = messages + [
        {"role": "assistant", "content": rawReply},
        {"role": "user", "content": f"這句 SQL 失敗了：{error}\n請修正後只輸出一句 SQL。"},
      ]
  return {"sql": sql, "columns": [], "rows": [], "error": str(lastError), "attempts": maxRetries + 1}
