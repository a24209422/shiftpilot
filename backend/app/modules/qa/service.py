import re
from datetime import datetime

import psycopg
from psycopg import Connection

from app.infra.actor import Actor
from app.infra.errors import AppError
from app.modules.qa import llm as llmModule
from app.modules.qa import prompt, sandbox, sqlguard

maxQuestionLength = 300


def callLlm(llm, model: str, messages: list[dict]) -> str:
  try:
    return llm(model, messages)
  except llmModule.LlmUnavailableError as error:
    raise AppError("QA_MODEL_UNAVAILABLE", error.message, 503)


def describeSqlError(error: Exception) -> str:
  if isinstance(error, psycopg.errors.QueryCanceled):
    return "查詢太久（超過 5 秒）"
  # PostgreSQL 的錯誤第二行之後是 LINE／HINT 這類細節，給模型看第一行就夠它修正
  return str(error).strip().split("\n")[0]


def composeAnswer(llm, model: str, question: str, columns: list[str], rows: list[list], truncated: bool) -> str:
  fallback = f"查到 {len(rows)}{' 筆以上' if truncated else ' 筆'}資料。"
  try:
    reply = llm(model, prompt.buildAnswerMessages(question, columns, rows, len(rows), truncated))
  except llmModule.LlmUnavailableError:
    # 回答句只是讓結果好讀；查詢已經成功，表格照樣給
    return fallback
  answer = re.sub(r"<think>.*?</think>", "", reply or "", flags=re.DOTALL).strip()
  return answer or fallback


def ask(
  conn: Connection, actor: Actor, question: str, model: str, qaDatabaseUrl: str | None, now: datetime, llm=llmModule.callModel
) -> dict:
  if not qaDatabaseUrl:
    raise AppError("QA_NOT_CONFIGURED", "問答還沒設定：請在 .env 設定 QA_DB_PASSWORD 並建立 qa_sandbox 帳號（見 README 的「問答」）", 503)
  question = (question or "").strip()
  if not question or len(question) > maxQuestionLength:
    raise AppError("VALIDATION", f"問題要 1 到 {maxQuestionLength} 個字", 422, {"field": "question"})
  models = {item["id"]: item for item in llmModule.listModels()}
  if model not in models:
    raise AppError("QA_UNKNOWN_MODEL", "沒有這個模型", 422, {"field": "model"})
  data = sandbox.collectSandboxData(conn, actor, now.date())
  messages = prompt.buildSqlMessages(question, data, now)
  sql, lastError, result = "", "", None
  with sandbox.openSandbox(qaDatabaseUrl, data) as sandboxConn:
    for _ in range(2):
      reply = callLlm(llm, model, messages)
      sql = sqlguard.extractSql(reply)
      try:
        sqlguard.validateSql(sql)
        result = sandbox.runQuery(sandboxConn, sql)
        break
      except (sqlguard.UnsafeSqlError, psycopg.Error) as error:
        lastError = describeSqlError(error)
        # 把錯誤訊息回饋給模型重試：小模型常拼錯欄位名稱，給它看錯誤通常一次就能修好
        messages = messages + [
          {"role": "assistant", "content": reply},
          {"role": "user", "content": f"這句 SQL 失敗了：{lastError}\n請修正後只輸出一句 SQL。"},
        ]
  if result is None:
    raise AppError("QA_QUERY_FAILED", f"查詢失敗：{lastError}", 422, {"sql": sql, "error": lastError})
  columns, rows, truncated = result
  return {
    "answer": composeAnswer(llm, model, question, columns, rows, truncated),
    "sql": sql, "columns": columns, "rows": rows, "truncated": truncated,
    "model": model, "remote": models[model]["remote"],
    "window": {"from": data.windowStart.isoformat(), "to": data.windowEnd.isoformat()},
  }
