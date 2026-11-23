import dataclasses
import logging
import os
import threading
from contextlib import contextmanager
from datetime import datetime

import psycopg
from psycopg import Connection

from app.infra.actor import Actor
from app.infra.errors import AppError
from app.modules.qa import llm as llmModule
from app.modules.qa import agent, assistant, jev, prompt, sandbox, sqlguard
from app.modules.qa.progress import EventSink, Progress
from app.modules.qa.proposals import findAsker, proposalNames
from app.modules.qa.tools import describeSqlError

logger = logging.getLogger(__name__)
maxQuestionLength = 300
# 伺服器不存對話，每次都把整段紀錄送給模型；不設上限，一次請求就能把 prompt 塞爆
maxHistoryEntries = 40
maxHistoryEntryLength = 1000
historyRoles = ("user", "assistant")

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


modes = ("pipeline", "agent", "jev", "assistant")


def resolveMode(mode: str | None) -> str:
  if mode is None:
    # 沒指定時預設舊流程：沒設 QA_MODE 的部署行為完全不變
    mode = os.getenv("QA_MODE", "").strip() or "pipeline"
  if mode not in modes:
    raise AppError("QA_NOT_CONFIGURED", "QA_MODE 只能是 pipeline、agent、jev 或 assistant", 503)
  return mode


def runPipeline(sandboxConn, llm, model: str, question: str, data, now: datetime, *, progress: Progress | None = None) -> dict:
  progress = progress or Progress()
  messages = prompt.buildSqlMessages(question, data, now)
  sql, lastError, result = "", "", None
  for _ in range(2):
    with progress.step("generate_query"):
      reply = callLlm(llm, model, messages)
      sql = sqlguard.extractSql(reply)
    try:
      with progress.step("query"):
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
  if result is None:
    raise AppError("QA_QUERY_FAILED", f"查詢失敗：{lastError}", 422, {"sql": sql, "error": lastError})
  columns, rows, truncated = result
  with progress.step("compose"):
    answer = composeAnswer(llm, model, question, columns, rows, truncated)
  return {
    "answer": answer,
    "sql": sql, "columns": columns, "rows": rows, "truncated": truncated,
  }


def runAgentMode(
  sandboxConn, toolLlm, model: str, question: str, data, now: datetime, decision: jev.JevDecision | None = None,
  *, progress: Progress | None = None,
) -> dict:
  # Jev 選中工具時只給那一個；退回（tool 是 None）或不是 jev 模式時三個工具都給
  allowedTools = [decision.tool] if decision and decision.tool else None
  try:
    outcome = agent.runAgent(sandboxConn, toolLlm, model, prompt.buildAgentMessages(question, data, now), allowedTools,
                             progress=progress)
  except llmModule.LlmUnavailableError as error:
    raise AppError("QA_MODEL_UNAVAILABLE", error.message, 503)
  extra = {
    "steps": outcome.steps, "toolCalls": outcome.toolCalls, "exhausted": outcome.exhausted,
    "promptTokens": outcome.promptTokens, "completionTokens": outcome.completionTokens,
  }
  if decision:
    extra["route"] = dataclasses.asdict(decision)
  if outcome.result is None:
    lastError = next((step["error"] for step in reversed(outcome.steps) if step["error"]), None) or "模型沒有呼叫工具"
    lastSql = next((step["arguments"].get("sql") for step in reversed(outcome.steps)
                    if step["tool"] == "run_sql" and isinstance(step["arguments"], dict)), None)
    raise AppError("QA_QUERY_FAILED", f"查詢失敗：{lastError}", 422, {
      "sql": lastSql if isinstance(lastSql, str) else "", "error": lastError,
      "steps": outcome.steps, "toolCalls": outcome.toolCalls, "exhausted": outcome.exhausted,
      **({"route": extra["route"]} if decision else {}),
    })
  result = outcome.result
  return {
    "answer": outcome.answer, "sql": result.sql or "", "columns": result.columns, "rows": result.rows, "truncated": result.truncated,
    **extra,
  }


def validateHistory(history) -> list[dict]:
  if history is None:
    return []
  # role 只收 user／assistant：讓使用者塞 system 訊息，等於讓他改掉助理規則
  valid = isinstance(history, list) and len(history) <= maxHistoryEntries and all(
    isinstance(entry, dict) and set(entry) == {"role", "content"} and entry["role"] in historyRoles
    and isinstance(entry["content"], str) and len(entry["content"]) <= maxHistoryEntryLength
    for entry in history
  )
  if not valid:
    raise AppError("VALIDATION", "對話紀錄格式不對或太長", 422, {"field": "history"})
  return [{"role": entry["role"], "content": entry["content"]} for entry in history]


def runAssistantMode(sandboxConn, toolLlm, model: str, question: str, history: list[dict], data, now: datetime, asker,
                     *, progress: Progress | None = None) -> dict:
  messages = prompt.buildAssistantMessages(question, history, data, now, asker)
  try:
    outcome = agent.runAgent(
      sandboxConn, toolLlm, model, messages, definitions=assistant.assistantToolDefinitions,
      execute=assistant.makeExecutor(data, asker), maxCalls=assistant.maxAssistantToolCalls,
      progress=progress, proposalTools=proposalNames,
    )
  except llmModule.LlmUnavailableError as error:
    raise AppError("QA_MODEL_UNAVAILABLE", error.message, 503)
  result = outcome.result
  # 反問、提議都不一定有查詢結果，所以只有三樣都沒有時才算失敗
  if not outcome.answer and result is None and outcome.proposal is None:
    raise AppError("QA_QUERY_FAILED", "助理沒有給出回答，請換個說法再試", 422, {"steps": outcome.steps})
  return {
    "answer": outcome.answer,
    "sql": (result.sql or "") if result else "", "columns": result.columns if result else [],
    "rows": result.rows if result else [], "truncated": result.truncated if result else False,
    "steps": outcome.steps, "toolCalls": outcome.toolCalls, "exhausted": outcome.exhausted,
    "promptTokens": outcome.promptTokens, "completionTokens": outcome.completionTokens,
    "proposal": outcome.proposal,
  }


def ask(
  conn: Connection, actor: Actor, question: str, model: str, qaDatabaseUrl: str | None, now: datetime, llm=llmModule.callModel,
  mode: str | None = None, toolLlm=llmModule.callModelWithTools, chooseTool=jev.chooseTool, jevConfigured=jev.isConfigured,
  history: list[dict] | None = None, *, onEvent: EventSink | None = None,
) -> dict:
  if not qaDatabaseUrl:
    raise AppError("QA_NOT_CONFIGURED", "問答還沒設定：請在 .env 設定 QA_DB_PASSWORD 並建立 qa_sandbox 帳號（見 README 的「問答」）", 503)
  mode = resolveMode(mode)
  if mode == "jev" and not jevConfigured():
    # 在拿名額、讀沙盒資料之前就擋下：沒設 key 的請求不該占用任何資源
    raise AppError("QA_NOT_CONFIGURED", "jev 模式還沒設定：請在 .env 填 JEV_API_KEY", 503)
  question = (question or "").strip()
  if not question or len(question) > maxQuestionLength:
    raise AppError("VALIDATION", f"問題要 1 到 {maxQuestionLength} 個字", 422, {"field": "question"})
  models = {item["id"]: item for item in llmModule.listModels()}
  if model not in models:
    raise AppError("QA_UNKNOWN_MODEL", "沒有這個模型", 422, {"field": "model"})
  # 其他模式一律不看 history，帶了也不驗證，行為才跟以前一樣
  history = validateHistory(history) if mode == "assistant" else []
  progress = Progress(onEvent)
  # 先拿名額再讀資料：被擋下的請求不用讀整包沙盒資料
  with questionSlot(actor.userId):
    progress.accepted()
    # 資料已全部讀進記憶體；LLM 呼叫可能長達數分鐘，不能一直持有 ACCESS SHARE 鎖擋住遷移或 DDL，
    # 也不該一直占著一條連線：之後只用沙盒連線，請求的連線先關掉（psycopg 離開 with 時遇到已關閉的連線會直接略過）
    with progress.step("prepare"):
      data = sandbox.collectSandboxData(conn, actor, now.date())
      conn.commit()
      conn.close()
    # Jev 不看資料，只看問題；先問完再開沙盒，等它的時候不占著沙盒連線
    decision = None
    if mode == "jev":
      with progress.step("route"):
        decision = chooseTool(question, now)
    try:
      with sandbox.openSandbox(qaDatabaseUrl, data) as sandboxConn:
        if mode == "assistant":
          asker = findAsker(data, actor.employeeId)
          body = runAssistantMode(sandboxConn, toolLlm, model, question, history, data, now, asker, progress=progress)
        elif mode in ("agent", "jev"):
          body = runAgentMode(sandboxConn, toolLlm, model, question, data, now, decision, progress=progress)
        else:
          body = runPipeline(sandboxConn, llm, model, question, data, now, progress=progress)
    except psycopg.OperationalError:
      # 兩種模式內的資料庫錯誤都已被接住，能走到這裡的只有開沙盒連線失敗；例外文字可能含主機與 port，只寫進伺服器 log
      logger.exception("問答沙盒連線失敗")
      raise AppError(
        "QA_SANDBOX_UNAVAILABLE",
        "問答沙盒帳號連不上：請確認 .env 的 QA_DB_PASSWORD 與資料庫裡的 qa_sandbox 帳號一致（見 README 的「問答」）",
        503,
      )
    return {
      **body, "mode": mode, "model": model, "remote": models[model]["remote"],
      "window": {"from": data.windowStart.isoformat(), "to": data.windowEnd.isoformat()},
    }
