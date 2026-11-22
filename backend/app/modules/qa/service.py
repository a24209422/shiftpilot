import logging
import threading
from contextlib import contextmanager
from datetime import datetime

import psycopg
from psycopg import Connection

from app.infra.actor import Actor
from app.infra.errors import AppError
from app.modules.qa import llm as llmModule
from app.modules.qa import prompt, sandbox, sqlguard
from app.modules.qa.tools import describeSqlError

logger = logging.getLogger(__name__)
maxQuestionLength = 300

# 一題最多要呼叫模型三次、可能好幾分鐘，期間占著一個執行緒與沙盒連線；不設上限，同時發問的人一多，其他 API 會排不到執行緒
# 名額記在記憶體裡，只在單一 process 有效（docker compose 只跑一個 uvicorn worker）
maxConcurrentQuestions = 3
askingUserIds: set[int] = set()
askingLock = threading.Lock()


@contextmanager
def questionSlot(userId: int):
  with askingLock:
    if userId in askingUserIds:
      raise AppError("QA_USER_BUSY", "上一題還在處理，請等它完成再問", 429)
    # 每人同時只有一題，所以人數就是正在處理的題數
    if len(askingUserIds) >= maxConcurrentQuestions:
      raise AppError("QA_BUSY", "問答目前忙碌中，請稍後再試", 429)
    askingUserIds.add(userId)
  try:
    yield
  finally:
    with askingLock:
      askingUserIds.discard(userId)


def callLlm(llm, model: str, messages: list[dict]) -> str:
  try:
    return llm(model, messages)
  except llmModule.LlmUnavailableError as error:
    raise AppError("QA_MODEL_UNAVAILABLE", error.message, 503)


def composeAnswer(llm, model: str, question: str, columns: list[str], rows: list[list], truncated: bool) -> str:
  fallback = f"查到 {len(rows)}{' 筆以上' if truncated else ' 筆'}資料。"
  try:
    reply = llm(model, prompt.buildAnswerMessages(question, columns, rows, len(rows), truncated))
  except llmModule.LlmUnavailableError:
    # 回答句只是讓結果好讀；查詢已經成功，表格照樣給
    return fallback
  answer = sqlguard.stripThink(reply).strip()
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
  # 先拿名額再讀資料：被擋下的請求不用讀整包沙盒資料
  with questionSlot(actor.userId):
    data = sandbox.collectSandboxData(conn, actor, now.date())
    # 資料已全部讀進記憶體；LLM 呼叫可能長達數分鐘，不能一直持有 ACCESS SHARE 鎖擋住遷移或 DDL，
    # 也不該一直占著一條連線：之後只用沙盒連線，請求的連線先關掉（psycopg 離開 with 時遇到已關閉的連線會直接略過）
    conn.commit()
    conn.close()
    messages = prompt.buildSqlMessages(question, data, now)
    sql, lastError, result = "", "", None
    try:
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
              {"role": "assistant", "content": reply or "（沒有輸出）"},
              {"role": "user", "content": f"這句 SQL 失敗了：{lastError}\n請修正後只輸出一句 SQL。"},
            ]
    except psycopg.OperationalError:
      # 迴圈內的資料庫錯誤都已被接住，能走到這裡的只有開沙盒連線失敗；例外文字可能含主機與 port，只寫進伺服器 log
      logger.exception("問答沙盒連線失敗")
      raise AppError(
        "QA_SANDBOX_UNAVAILABLE",
        "問答沙盒帳號連不上：請確認 .env 的 QA_DB_PASSWORD 與資料庫裡的 qa_sandbox 帳號一致（見 README 的「問答」）",
        503,
      )
    if result is None:
      raise AppError("QA_QUERY_FAILED", f"查詢失敗：{lastError}", 422, {"sql": sql, "error": lastError})
    columns, rows, truncated = result
    return {
      "answer": composeAnswer(llm, model, question, columns, rows, truncated),
      "sql": sql, "columns": columns, "rows": rows, "truncated": truncated,
      "model": model, "remote": models[model]["remote"],
      "window": {"from": data.windowStart.isoformat(), "to": data.windowEnd.isoformat()},
    }
