"""自然語言 → SQLite 查詢。只產生並執行唯讀的 SELECT。"""
import os
import re
import sqlite3
from datetime import datetime, timedelta

import requests

import db

weekdayNames = ["一", "二", "三", "四", "五", "六", "日"]
forbiddenPattern = re.compile(
  r"\b(insert|update|delete|drop|alter|create|attach|detach|pragma|vacuum|reindex)\b",
  re.IGNORECASE,
)


class UnsafeSqlError(ValueError):
  pass


def getOllamaConfig():
  return {
    "url": os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/"),
    "model": os.getenv("OLLAMA_MODEL", "qwen2.5:3b"),
  }


def callOllama(messages, model=None, url=None):
  config = getOllamaConfig()
  response = requests.post(
    f"{url or config['url']}/api/chat",
    json={
      "model": model or config["model"],
      "messages": messages,
      "stream": False,
      # 溫度設 0：同一個問題盡量產生同一句 SQL，結果比較穩定也比較好除錯
      "options": {"temperature": 0},
    },
    timeout=180,
  )
  response.raise_for_status()
  return response.json()["message"]["content"]


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

  systemPrompt = f"""你是 SQLite 專家，負責把使用者的中文問題轉成一句 SQLite 查詢。

規則：
1. 只輸出一句 SELECT（或 WITH ... SELECT），放在 ```sql 區塊裡，不要任何解釋。
2. 只能使用下方 schema 裡的資料表與欄位。排程相關的問題都查 event_details，不需要 JOIN。
3. 時間欄位是文字，格式 'YYYY-MM-DD HH:MM'。取日期用 date(start_at)，取時間用 time(start_at)，可以直接用字串比較。
4. 不要用 date('now')，日期一律以下方「日期參考」為準。
5. 比對名稱或標題時用 LIKE '%關鍵字%'，因為使用者常只講部分名字。
6. 列出排程時帶出 resource_name，並依 start_at 排序，讓結果看得懂。
7. 使用者提到排程名稱（例如「晚班」「週會」）時，用 title LIKE 比對，不要自己推算時段。
8. 「人」「每個人」「員工」指 resource_type = 'person'；「會議室」指 'room'；「設備」指 'equipment'。查 resources 表時欄位是 type。
9. event_details 裡一筆排程有幾個資源就有幾列。計算「幾筆排程」「幾場會議」時用 COUNT(DISTINCT event_id)，不要用 COUNT(*)。

## Schema
{schemaText}

## 目前資料中的值
- category：{', '.join(vocabulary['categories']) or '（尚無）'}
- resource_type（resources.type）：{', '.join(vocabulary['resourceTypes']) or '（尚無）'}
- resource_name（resources.name）：{', '.join(vocabulary['resourceNames']) or '（尚無）'}

## 日期參考
{buildDateReference(now)}
"""
  # few-shot 範例的日期跟著今天變，模型才學得到「明天」「下週」要換成實際日期
  fewShots = [
    (
      "明天小明有什麼行程？",
      "SELECT resource_name, title, start_at, end_at\n"
      "FROM event_details\n"
      f"WHERE resource_name LIKE '%小明%' AND date(start_at) = '{tomorrow}'\n"
      "ORDER BY start_at",
    ),
    (
      "下週總共有幾場會議？",
      "SELECT COUNT(DISTINCT event_id) AS meeting_count\n"
      "FROM event_details\n"
      f"WHERE category = 'meeting' AND date(start_at) BETWEEN '{nextMonday}' AND '{nextSunday}'",
    ),
  ]
  messages = [{"role": "system", "content": systemPrompt}]
  for exampleQuestion, exampleSql in fewShots:
    messages.append({"role": "user", "content": exampleQuestion})
    messages.append({"role": "assistant", "content": f"```sql\n{exampleSql}\n```"})
  messages.append({"role": "user", "content": question})
  return messages


def answerQuestion(question, dbPath, now=None, llm=None, maxRetries=1):
  now = now or datetime.now()
  llm = llm or callOllama
  messages = buildMessages(question, db.getLlmSchemaText(), db.getVocabulary(dbPath), now)
  sql, lastError = "", None
  for attempt in range(1, maxRetries + 2):
    rawReply = llm(messages)
    sql = extractSql(rawReply)
    try:
      validateSql(sql)
      columns, rows = db.runReadOnlyQuery(dbPath, sql)
      return {"sql": sql, "columns": columns, "rows": rows, "error": None, "attempts": attempt}
    except (UnsafeSqlError, sqlite3.Error) as error:
      lastError = error
      # 把錯誤訊息回饋給模型重試：小模型常拼錯欄位名稱，給它看錯誤通常一次就能修好
      messages = messages + [
        {"role": "assistant", "content": rawReply},
        {"role": "user", "content": f"這句 SQL 失敗了：{error}\n請修正後只輸出一句 SQL。"},
      ]
  return {"sql": sql, "columns": [], "rows": [], "error": str(lastError), "attempts": maxRetries + 1}
