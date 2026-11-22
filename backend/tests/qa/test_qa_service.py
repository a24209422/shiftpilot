from datetime import datetime

from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest

from app.infra.db import openDb
from app.infra.errors import AppError
from app.modules.qa import sandbox, service
from app.modules.qa.jev import JevDecision
from app.modules.qa.llm import LlmUnavailableError, ToolCall, ToolReply
from tests.leave.world import makeWorld

now = datetime(2026, 11, 21, 10)


@pytest.fixture(autouse=True)
def localModelsOnly(monkeypatch):
  monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:3b")
  monkeypatch.delenv("QA_MODE", raising=False)
  for name in ("LOCAL_MODELS", "OPENROUTER_API_KEY", "GOOGLE_AI_API_KEY"):
    monkeypatch.setenv(name, "")


@pytest.fixture
def world(migratedUrl, qaSandboxUrl):
  w = makeWorld(migratedUrl)
  w.qaUrl = qaSandboxUrl
  return w


def scripted(*replies):
  calls = []

  def fake(model, messages):
    calls.append(messages)
    reply = replies[len(calls) - 1]
    if isinstance(reply, Exception):
      raise reply
    return reply

  fake.calls = calls
  return fake


def ask(w, llm, question="有哪些員工？", qaUrl="default", model="qwen2.5:3b", actor=None, mode=None, toolLlm=None):
  with openDb(w.url) as conn:
    return service.ask(
      conn, actor or w.bobActor, question, model, w.qaUrl if qaUrl == "default" else qaUrl, now, llm=llm,
      mode=mode, toolLlm=toolLlm or unusedToolLlm,
    )


def unusedToolLlm(model, messages, tools):
  raise AssertionError("舊流程不該呼叫 tool calling")


def expectError(code, call, *args, **kwargs):
  with pytest.raises(AppError) as info:
    call(*args, **kwargs)
  assert info.value.code == code
  return info.value


def testSuccessReturnsAnswerTableAndWindow(world):
  llm = scripted("```sql\nSELECT name FROM employees ORDER BY name\n```", "目前有四位員工。")
  result = ask(world, llm)
  assert result["answer"] == "目前有四位員工。"
  assert result["sql"] == "SELECT name FROM employees ORDER BY name"
  assert result["columns"] == ["name"] and len(result["rows"]) == 4 and result["truncated"] is False
  assert result["model"] == "qwen2.5:3b" and result["remote"] is False
  assert result["window"] == {"from": "2026-08-23", "to": "2027-02-19"}
  # 回答句那次呼叫看得到問題與查詢結果
  assert "有哪些員工？" in llm.calls[1][-1]["content"] and "alice" in llm.calls[1][-1]["content"]


def testSqlErrorIsFedBackAndRetried(world):
  llm = scripted("SELECT nope FROM employees", "SELECT name FROM employees", "四位。")
  result = ask(world, llm)
  assert result["sql"] == "SELECT name FROM employees"
  assert "這句 SQL 失敗了" in llm.calls[1][-1]["content"]


def testUnsafeSqlIsRetried(world):
  llm = scripted("SELECT set_config('role', 'schedule_app', false)", "SELECT count(*) FROM employees", "四位。")
  assert ask(world, llm)["rows"] == [[4]]


def testFailsAfterOneRetry(world):
  error = expectError("QA_QUERY_FAILED", ask, world, scripted("SELECT nope FROM employees", "SELECT still_nope FROM employees"))
  assert error.status == 422 and error.details["sql"] == "SELECT still_nope FROM employees" and error.details["error"]


def testModelUnavailable(world):
  error = expectError("QA_MODEL_UNAVAILABLE", ask, world, scripted(LlmUnavailableError("無法呼叫 Ollama：refused")))
  assert error.status == 503 and "Ollama" in error.message


def testAnswerFallsBackWhenSecondCallFails(world):
  result = ask(world, scripted("SELECT name FROM employees", LlmUnavailableError("timeout")))
  assert result["answer"] == "查到 4 筆資料。"


def testEmptyResultAnswerStillComesFromModel(world):
  result = ask(world, scripted("SELECT name FROM employees WHERE name = 'nobody'", "查無資料。"))
  assert result["rows"] == [] and result["answer"] == "查無資料。"


def testSandboxLoginFailureIs503WithoutLeakingDetails(world):
  parts = urlsplit(world.qaUrl)
  badUrl = urlunsplit(parts._replace(netloc=f"{parts.username}:wrongpassword@{parts.hostname}:{parts.port}" if parts.port else f"{parts.username}:wrongpassword@{parts.hostname}"))
  error = expectError("QA_SANDBOX_UNAVAILABLE", ask, world, scripted("SELECT 1"), qaUrl=badUrl)
  assert error.status == 503
  assert parts.hostname not in error.message and "wrongpassword" not in error.message and "password authentication" not in error.message


def testNotConfigured(world):
  assert expectError("QA_NOT_CONFIGURED", ask, world, scripted(), qaUrl=None).status == 503


def testUnknownModel(world):
  expectError("QA_UNKNOWN_MODEL", ask, world, scripted(), model="gpt-x")


@pytest.mark.parametrize("question", ["", "   ", "問" * 301])
def testQuestionLength(world, question):
  expectError("VALIDATION", ask, world, scripted(), question=question)


def testPromptMentionsWindowVocabularyAndDates(world):
  llm = scripted("SELECT 1", "好。")
  ask(world, llm)
  system = llm.calls[0][0]["content"]
  assert "2026-08-23" in system and "2027-02-19" in system
  assert "工程部" in system and "標準班" in system and "事假" in system
  assert "2026-11-22 星期日（明天）" in system


@pytest.mark.parametrize("reply", ["<think>想想</think>", "<think>想到一半 好的，共 4 筆", None, ""])
def testUnusableAnswerReplyFallsBack(world, reply):
  result = ask(world, scripted("SELECT name FROM employees", reply))
  assert result["answer"] == "查到 4 筆資料。"


def testClosedThinkIsStrippedFromAnswer(world):
  result = ask(world, scripted("SELECT name FROM employees", "<think>推理</think>四位。"))
  assert result["answer"] == "四位。"


def testRequestConnectionClosedDuringLlmCalls(world):
  closedStates = []
  with openDb(world.url) as conn:
    def fake(model, messages):
      closedStates.append(conn.closed)
      return "SELECT name FROM employees" if len(closedStates) == 1 else "好。"

    service.ask(conn, world.bobActor, "有哪些員工？", "qwen2.5:3b", world.qaUrl, now, llm=fake)
  assert closedStates == [True, True]


def askDuringFirstQuestion(w, secondActor):
  # 第一題（bob）還在等模型回覆時送出第二題，回傳第二題的結果
  second = {}

  def firstLlm(model, messages):
    if "result" not in second:
      second["result"] = ask(w, scripted("SELECT 1", "好。"), actor=secondActor)
      return "SELECT name FROM employees"
    return "好。"

  ask(w, firstLlm)
  return second["result"]


def testSameUserCannotAskWhileQuestionRunning(world):
  error = expectError("QA_USER_BUSY", askDuringFirstQuestion, world, world.bobActor)
  assert error.status == 429


def testAskRejectedWhenAllSlotsBusy(world, monkeypatch):
  monkeypatch.setattr(service, "maxConcurrentQuestions", 1)
  error = expectError("QA_BUSY", askDuringFirstQuestion, world, world.aliceActor)
  assert error.status == 429


def testOtherUserCanAskWhileSlotsRemain(world):
  assert askDuringFirstQuestion(world, world.aliceActor)["rows"] == [[1]]


def testSlotReleasedAfterFailedQuestion(world):
  expectError("QA_MODEL_UNAVAILABLE", ask, world, scripted(LlmUnavailableError("無法呼叫 Ollama：refused")))
  assert ask(world, scripted("SELECT 1", "好。"))["rows"] == [[1]]


def testRetryFeedbackContainsErrorAndPreviousReply(world):
  llm = scripted("SELECT nope FROM employees", "SELECT name FROM employees", "好。")
  ask(world, llm)
  retry = llm.calls[1]
  assert retry[-2] == {"role": "assistant", "content": "SELECT nope FROM employees"}
  assert "nope" in retry[-1]["content"]


def testUnsafeRetryFeedback(world):
  llm = scripted("SELECT set_config('role', 'x', false)", "SELECT name FROM employees", "好。")
  ask(world, llm)
  assert llm.calls[1][-2]["content"] == "SELECT set_config('role', 'x', false)"
  assert "這句 SQL 失敗了" in llm.calls[1][-1]["content"]


def testEmptyReplyUsesPlaceholderOnRetry(world):
  llm = scripted("", "SELECT name FROM employees", "好。")
  ask(world, llm)
  assert llm.calls[1][-2] == {"role": "assistant", "content": "（沒有輸出）"}


def testAnswerPromptOnlyIncludesFirstThirtyRows(world):
  llm = scripted("SELECT generate_series(1, 40) AS n", "好。")
  ask(world, llm)
  content = llm.calls[1][-1]["content"]
  assert "前 30 列" in content and "[30]" in content and "[31]" not in content and "總筆數：40 筆" in content


def testQueryCanceledMapsToTimeoutMessage(world, monkeypatch):
  def cancel(conn, sql):
    raise psycopg.errors.QueryCanceled("canceling statement due to statement timeout")

  monkeypatch.setattr(sandbox, "runQuery", cancel)
  error = expectError("QA_QUERY_FAILED", ask, world, scripted("SELECT 1", "SELECT 2"))
  assert error.details["error"] == "查詢太久（超過 5 秒）"


def testDateReferenceCoversTwoWeeksEachSide(world):
  llm = scripted("SELECT 1", "好。")
  ask(world, llm)
  system = llm.calls[0][0]["content"]
  assert "2026-11-07 星期六" in system and "2026-12-05 星期六" in system


def toolScript(*replies):
  calls, toolSets = [], []

  def fake(model, messages, tools):
    calls.append(list(messages))
    toolSets.append([item["function"]["name"] for item in tools])
    item = replies[len(calls) - 1]
    if isinstance(item, Exception):
      raise item
    return item

  fake.calls = calls
  fake.toolSets = toolSets
  return fake


def sqlCall(sql):
  return ToolReply("", [ToolCall("c1", "run_sql", {"sql": sql}, "")], 10, 2)


def testDefaultModeIsPipeline(world):
  assert ask(world, scripted("SELECT 1 AS n", "一。"))["mode"] == "pipeline"


def testEnvModeAgent(world, monkeypatch):
  monkeypatch.setenv("QA_MODE", "agent")
  toolLlm = toolScript(sqlCall("SELECT name FROM employees"), ToolReply("四位。", [], 5, 1))
  result = ask(world, scripted(), toolLlm=toolLlm)
  assert result["mode"] == "agent" and len(toolLlm.calls) == 2


def testBodyModeOverridesEnv(world, monkeypatch):
  monkeypatch.setenv("QA_MODE", "agent")
  assert ask(world, scripted("SELECT 1 AS n", "一。"), mode="pipeline")["mode"] == "pipeline"


def testBadEnvMode(world, monkeypatch):
  monkeypatch.setenv("QA_MODE", "foo")
  expectError("QA_NOT_CONFIGURED", ask, world, scripted())


def testAgentSuccessShape(world):
  toolLlm = toolScript(sqlCall("SELECT name FROM employees ORDER BY name"), ToolReply("四位。", [], 5, 1))
  result = ask(world, scripted(), mode="agent", toolLlm=toolLlm)
  assert result["answer"] == "四位。" and result["mode"] == "agent" and result["columns"] == ["name"] and len(result["rows"]) == 4
  assert result["sql"] == "SELECT name FROM employees ORDER BY name" and result["toolCalls"] == 1 and result["exhausted"] is False
  assert result["steps"] == [{"tool": "run_sql", "arguments": {"sql": "SELECT name FROM employees ORDER BY name"}, "rowCount": 4, "error": None}]
  assert (result["promptTokens"], result["completionTokens"]) == (15, 3)
  assert result["window"] and result["remote"] is False
  system = toolLlm.calls[0][0]["content"]
  assert "find_available_people" in system


def testAgentFixedToolResultHasEmptySql(world):
  call = ToolReply("", [ToolCall("c1", "get_busy_periods", {"start": "2026-11-21", "end": "2026-11-22"}, "")], None, None)
  result = ask(world, scripted(), mode="agent", toolLlm=toolScript(call, ToolReply("沒有。", [], None, None)))
  assert result["sql"] == "" and result["columns"] == ["who", "start_at", "end_at", "kind", "label"]


def testAgentNoResultIsQueryFailed(world):
  error = expectError("QA_QUERY_FAILED", ask, world, scripted(), mode="agent", toolLlm=toolScript(ToolReply("直接回答", [], None, None)))
  assert error.details["toolCalls"] == 0 and error.details["exhausted"] is False and error.details["sql"] == ""
  assert "模型沒有呼叫工具" in error.message


def testAgentAllToolsFailedKeepsLastSql(world):
  toolLlm = toolScript(sqlCall("SELECT nope FROM employees"), ToolReply("算了", [], None, None))
  error = expectError("QA_QUERY_FAILED", ask, world, scripted(), mode="agent", toolLlm=toolLlm)
  assert error.details["sql"] == "SELECT nope FROM employees" and "nope" in error.details["error"]
  assert error.details["steps"][0]["error"]


def testAgentModelUnavailable(world):
  toolLlm = toolScript(LlmUnavailableError("無法呼叫 Ollama：refused"))
  error = expectError("QA_MODEL_UNAVAILABLE", ask, world, scripted(), mode="agent", toolLlm=toolLlm)
  assert error.status == 503


def testAgentReleasesSlot(world):
  expectError("QA_QUERY_FAILED", ask, world, scripted(), mode="agent", toolLlm=toolScript(ToolReply("x", [], None, None)))
  assert ask(world, scripted("SELECT 1", "好。"))["rows"] == [[1]]


def askJev(w, toolLlm, decision=None, configured=True, **kwargs):
  asked = []

  def chooser(question, when):
    asked.append(question)
    if decision is None:
      raise AssertionError("不該呼叫 Jev")
    return decision

  with openDb(w.url) as conn:
    result = service.ask(
      conn, kwargs.get("actor") or w.bobActor, "有哪些員工？", "qwen2.5:3b", w.qaUrl, now, llm=scripted(),
      mode="jev", toolLlm=toolLlm, chooseTool=chooser, jevConfigured=lambda: configured,
    )
  return result, asked


def chosen(tool="run_sql", reason=None):
  return JevDecision(tool, 0.9 if tool else 0.3, reason, 439, 0.2)


def testJevModeUsesChosenTool(world):
  toolLlm = toolScript(sqlCall("SELECT name FROM employees ORDER BY name"), ToolReply("四位。", [], 5, 1))
  result, asked = askJev(world, toolLlm, chosen("run_sql"))
  assert result["mode"] == "jev" and asked == ["有哪些員工？"]
  assert toolLlm.toolSets[0] == ["run_sql"]
  assert result["route"] == {"tool": "run_sql", "confidence": 0.9, "fallbackReason": None, "promptTokens": 439, "seconds": 0.2}
  assert result["toolCalls"] == 1 and result["steps"][0]["tool"] == "run_sql"


def testJevFallbackRunsFullAgent(world):
  toolLlm = toolScript(sqlCall("SELECT name FROM employees"), ToolReply("四位。", [], 5, 1))
  result, _ = askJev(world, toolLlm, chosen(None, "low_confidence"))
  assert toolLlm.toolSets[0] == ["run_sql", "find_available_people", "get_busy_periods"]
  assert result["route"]["tool"] is None and result["route"]["fallbackReason"] == "low_confidence"


def testJevUnavailableRunsFullAgent(world):
  toolLlm = toolScript(sqlCall("SELECT name FROM employees"), ToolReply("四位。", [], 5, 1))
  result, _ = askJev(world, toolLlm, chosen(None, "unavailable"))
  assert result["answer"] == "四位。" and result["route"]["fallbackReason"] == "unavailable"


def testJevWithoutKey(world):
  error = expectError("QA_NOT_CONFIGURED", askJev, world, toolScript(), None, False)
  assert error.status == 503 and "JEV_API_KEY" in error.message
  # 沒佔名額：之後的問題照常能問
  assert service.askingUserIds == set()


def testJevQueryFailedHasRoute(world):
  toolLlm = toolScript(sqlCall("SELECT nope FROM employees"), ToolReply("算了", [], None, None))
  error = expectError("QA_QUERY_FAILED", askJev, world, toolLlm, chosen("run_sql"))
  assert error.details["route"]["tool"] == "run_sql"


def testQaModeEnvAcceptsJev(monkeypatch):
  monkeypatch.setenv("QA_MODE", "jev")
  assert service.resolveMode(None) == "jev"
