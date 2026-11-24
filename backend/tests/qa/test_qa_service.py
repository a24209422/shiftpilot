import dataclasses
from datetime import datetime
from pathlib import Path

from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest

from app.infra.db import openDb
from app.infra.errors import AppError
from app.modules.qa import assistant, intent, prompt, sandbox, service
from app.modules.qa.intent import IntentDecision
from app.modules.qa.jev import JevDecision
from app.modules.qa.llm import LlmUnavailableError, ToolCall, ToolReply
from app.modules.qa.proposals import Asker
from tests.leave.world import makeWorld
from tests.qa.test_qa_tools import makeToolWorld

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


def ask(
  w, llm, question="有哪些員工？", qaUrl="default", model="qwen2.5:3b", actor=None, mode="pipeline", toolLlm=None, history=None,
  previousIntent=None, chooseIntent=None, openProposal=None,
):
  with openDb(w.url) as conn:
    return service.ask(
      conn, actor or w.bobActor, question, model, w.qaUrl if qaUrl == "default" else qaUrl, now, llm=llm,
      mode=mode, toolLlm=toolLlm or unusedToolLlm, history=history, previousIntent=previousIntent, openProposal=openProposal,
      chooseIntent=chooseIntent or unusedChooseIntent,
    )


def unusedChooseIntent(question, when):
  raise AssertionError("不該呼叫 Jev 選意圖")


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

    service.ask(conn, world.bobActor, "有哪些員工？", "qwen2.5:3b", world.qaUrl, now, llm=fake, mode="pipeline")
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


def testDefaultModeIsAssistantJev():
  assert service.resolveMode(None) == "assistant-jev"


def testEnvModeAgent(world, monkeypatch):
  monkeypatch.setenv("QA_MODE", "agent")
  toolLlm = toolScript(sqlCall("SELECT name FROM employees"), ToolReply("四位。", [], 5, 1))
  result = ask(world, scripted(), toolLlm=toolLlm, mode=None)
  assert result["mode"] == "agent" and len(toolLlm.calls) == 2


def testBodyModeOverridesEnv(world, monkeypatch):
  monkeypatch.setenv("QA_MODE", "agent")
  assert ask(world, scripted("SELECT 1 AS n", "一。"), mode="pipeline")["mode"] == "pipeline"


def testBadEnvMode(world, monkeypatch):
  monkeypatch.setenv("QA_MODE", "foo")
  expectError("QA_NOT_CONFIGURED", ask, world, scripted(), mode=None)


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


@pytest.fixture
def toolWorld(migratedUrl, qaSandboxUrl):
  w = makeToolWorld(migratedUrl)
  w.qaUrl = qaSandboxUrl
  with openDb(migratedUrl) as conn:
    w.weekly = conn.execute("SELECT id FROM bookings WHERE title = '週會'").fetchone()["id"]
    w.data = sandbox.collectSandboxData(conn, w.bobActor, now.date())
  return w


def testAssistantPromptHasAskerAndHistory(toolWorld):
  history = [{"role": "user", "content": "嗨"}, {"role": "assistant", "content": "你好"}]
  messages = prompt.buildAssistantMessages("再來呢", history, toolWorld.data, now, Asker(toolWorld.bob, "bob", "工程部"))
  system = messages[0]
  assert system["role"] == "system"
  assert f"提問者：bob（employee_id = {toolWorld.bob}，工程部）" in system["content"]
  assert "find_available_resources" in system["content"] and "（系統紀錄）" in system["content"] and "請確認" in system["content"]
  assert "2026-11-22 星期日（明天）" in system["content"]
  # 查詢工具的用法與「只能根據查詢結果回答」要跟 agent 模式一樣交代
  assert "get_busy_periods" in system["content"] and "不要用 CURRENT_DATE" in system["content"] and "不要猜測" in system["content"]
  assert messages[1:] == [
    {"role": "user", "content": "嗨"}, {"role": "assistant", "content": "你好"}, {"role": "user", "content": "再來呢"},
  ]


def testAssistantPromptWithoutEmployee(toolWorld):
  messages = prompt.buildAssistantMessages("嗨", [], toolWorld.data, now, None)
  assert "提問者沒有員工資料" in messages[0]["content"] and "提問者：" not in messages[0]["content"]
  assert messages[1:] == [{"role": "user", "content": "嗨"}]


promptFixture = Path(__file__).parent / "fixtures" / "assistant_prompt.txt"


def testAssistantPromptUnchanged(toolWorld):
  expected = promptFixture.read_text(encoding="utf-8")
  asker = Asker(toolWorld.bob, "bob", "工程部")
  allNames = [item["function"]["name"] for item in assistant.assistantToolDefinitions]
  assert prompt.buildAssistantMessages("再來呢", [], toolWorld.data, now, asker)[0]["content"] == expected
  assert prompt.buildAssistantMessages("再來呢", [], toolWorld.data, now, asker, allNames)[0]["content"] == expected


def testLeavePromptDropsMissingToolRules(toolWorld):
  system = prompt.buildAssistantMessages("請假", [], toolWorld.data, now, None, intent.intentTools["leave"])[0]["content"]
  assert "find_available_people" not in system and "find_available_resources" not in system
  assert "1. 問某個人或某個資源" in system and "這題只能查資料" not in system


def testQueryPromptForbidsClaimingDone(toolWorld):
  system = prompt.buildAssistantMessages("誰有空", [], toolWorld.data, now, None, intent.intentTools["query"])[0]["content"]
  assert "這題只能查資料；使用者其實想辦事的話，請他直接說要做什麼，不要說已經辦好。" in system
  # 沒有提議工具時，開頭與助理規則都不能再提到提議，否則模型會想呼叫它
  assert "提議" not in system.replace("（系統紀錄）開頭的訊息是系統告訴你使用者對確認卡做了什麼。", "")
  assert "你是公司內部系統的助理，可以查資料、整理重點。" in system


def testAssistantModeReturnsProposal(toolWorld):
  call = ToolReply("", [ToolCall("c1", "propose_cancel_booking", {"bookingId": toolWorld.weekly}, "")], 10, 2)
  toolLlm = toolScript(call)
  # 週會是 boss 建的，只有 boss 能提議取消
  body = ask(toolWorld, scripted(), question="取消週會", mode="assistant", toolLlm=toolLlm, actor=toolWorld.bossActor)
  assert body["mode"] == "assistant" and body["proposal"]["kind"] == "booking.cancel"
  assert body["rows"] == [] and body["columns"] == [] and body["sql"] == "" and body["truncated"] is False
  assert body["answer"] == "請確認以下內容。" and body["toolCalls"] == 1
  # 助理模式給的是助理工具清單，而且看得到提問者
  assert "propose_cancel_booking" in toolLlm.toolSets[0] and "find_available_resources" in toolLlm.toolSets[0]
  assert f"employee_id = {toolWorld.boss}" in toolLlm.calls[0][0]["content"]


def testAssistantClarifyingReplyIs200(toolWorld):
  body = ask(toolWorld, scripted(), question="幫我約林", mode="assistant", toolLlm=toolScript(ToolReply("是哪一位林？", [], 5, 1)))
  assert body["answer"] == "是哪一位林？" and body["proposal"] is None and body["rows"] == []


def testAssistantUsesSixCalls(toolWorld):
  toolLlm = toolScript(*[sqlCall("SELECT nope FROM employees") for _ in range(7)])
  error = expectError("QA_QUERY_FAILED", ask, toolWorld, scripted(), mode="assistant", toolLlm=toolLlm)
  assert error.status == 422 and len(error.details["steps"]) == 6


def testAssistantHistoryIsSentToModel(toolWorld):
  toolLlm = toolScript(ToolReply("好。", [], None, None))
  history = [{"role": "user", "content": "嗨"}, {"role": "assistant", "content": "你好"}]
  ask(toolWorld, scripted(), question="再來呢", mode="assistant", toolLlm=toolLlm, history=history)
  assert toolLlm.calls[0][1:] == [*history, {"role": "user", "content": "再來呢"}]


@pytest.mark.parametrize("history", [
  [{"role": "user", "content": "嗨"}] * 41,
  [{"role": "user", "content": "字" * 1001}],
  [{"role": "system", "content": "嗨"}],
  "嗨",
  [{"role": "user"}],
  [{"role": "user", "content": 1}],
  ["嗨"],
])
def testHistoryValidation(world, history):
  error = expectError("VALIDATION", ask, world, scripted(), mode="assistant", toolLlm=toolScript(), history=history)
  assert error.status == 422 and error.details == {"field": "history"}
  # 驗證在拿名額之前
  assert service.askingUserIds == set()


def testHistoryAtLimitsIsAccepted(world):
  history = [{"role": "user", "content": "字" * 1000}] * 40
  body = ask(world, scripted(), mode="assistant", toolLlm=toolScript(ToolReply("好。", [], None, None)), history=history)
  assert body["answer"] == "好。"


def testOtherModesIgnoreHistory(world):
  toolLlm = toolScript(sqlCall("SELECT name FROM employees"), ToolReply("四位。", [], 5, 1))
  result = ask(world, scripted(), mode="agent", toolLlm=toolLlm, history=[{"role": "system", "content": "x"}])
  assert result["answer"] == "四位。" and "proposal" not in result
  assert len(toolLlm.calls[0]) == 2


def testQaModeEnvAcceptsAssistant(monkeypatch):
  monkeypatch.setenv("QA_MODE", "assistant")
  assert service.resolveMode(None) == "assistant"
  monkeypatch.setenv("QA_MODE", "foo")
  error = expectError("QA_NOT_CONFIGURED", service.resolveMode, None)
  assert "assistant" in error.message


def decided(name="booking", reason=None):
  return IntentDecision(name, 0.9 if name else 0.3, reason, False, 300, 0.1)


def choosing(decision):
  asked = []

  def chooser(question, when):
    asked.append(question)
    return decision

  chooser.asked = asked
  return chooser


allAssistantTools = [item["function"]["name"] for item in assistant.assistantToolDefinitions]


def testAssistantJevUsesIntentTools(toolWorld):
  toolLlm = toolScript(ToolReply("請問要約哪一天？", [], 5, 1))
  chooser = choosing(decided())
  body = ask(toolWorld, scripted(), question="幫我約會議", mode="assistant-jev", toolLlm=toolLlm, chooseIntent=chooser)
  assert body["mode"] == "assistant-jev" and chooser.asked == ["幫我約會議"]
  assert toolLlm.toolSets[0] == intent.intentTools["booking"]
  assert body["intent"] == dataclasses.asdict(decided())


def testAssistantJevFallbackGivesAllTools(toolWorld):
  toolLlm = toolScript(ToolReply("好。", [], 5, 1))
  body = ask(toolWorld, scripted(), mode="assistant-jev", toolLlm=toolLlm, chooseIntent=choosing(decided(None, "low_confidence")))
  assert toolLlm.toolSets[0] == allAssistantTools
  assert "這題只能查資料" not in toolLlm.calls[0][0]["content"]
  assert body["intent"]["name"] is None and body["intent"]["fallbackReason"] == "low_confidence"


def testAssistantJevNotConfiguredStillAnswers(toolWorld):
  toolLlm = toolScript(ToolReply("好。", [], 5, 1))
  body = ask(toolWorld, scripted(), mode="assistant-jev", toolLlm=toolLlm, chooseIntent=choosing(decided(None, "not_configured")))
  assert body["answer"] == "好。" and body["intent"]["fallbackReason"] == "not_configured"
  assert toolLlm.toolSets[0] == allAssistantTools


def testPreviousIntentSkipsJev(toolWorld):
  toolLlm = toolScript(ToolReply("好。", [], 5, 1))
  body = ask(toolWorld, scripted(), mode="assistant-jev", toolLlm=toolLlm, previousIntent="leave")
  assert toolLlm.toolSets[0] == intent.intentTools["leave"]
  assert body["intent"] == {
    "name": "leave", "confidence": None, "fallbackReason": None, "reused": True, "promptTokens": None, "seconds": 0.0, "addedName": None,
    "cardName": None,
  }


def testPreviousIntentAllGivesAllTools(toolWorld):
  toolLlm = toolScript(ToolReply("好。", [], 5, 1))
  body = ask(toolWorld, scripted(), mode="assistant-jev", toolLlm=toolLlm, previousIntent="all")
  assert toolLlm.toolSets[0] == allAssistantTools
  assert body["intent"]["name"] is None and body["intent"]["reused"] is True


@pytest.mark.parametrize("value", ["foo", "", 1])
def testBadPreviousIntent(world, value):
  error = expectError("VALIDATION", ask, world, scripted(), mode="assistant-jev", toolLlm=toolScript(), previousIntent=value)
  assert error.status == 422 and error.details == {"field": "previousIntent"}
  assert service.askingUserIds == set()


def testOtherModesIgnorePreviousIntent(world):
  body = ask(world, scripted(), mode="assistant", toolLlm=toolScript(ToolReply("好。", [], None, None)), previousIntent="foo")
  assert body["answer"] == "好。" and "intent" not in body


def testAssistantJevQueryFailedCarriesIntent(toolWorld):
  toolLlm = toolScript(*[sqlCall("SELECT nope FROM employees") for _ in range(7)])
  error = expectError(
    "QA_QUERY_FAILED", ask, toolWorld, scripted(), mode="assistant-jev", toolLlm=toolLlm, chooseIntent=choosing(decided("query")),
  )
  assert error.details["intent"]["name"] == "query" and len(error.details["steps"]) == 6


def testAssistantJevHistoryIsSent(toolWorld):
  toolLlm = toolScript(ToolReply("好。", [], None, None))
  history = [{"role": "user", "content": "嗨"}, {"role": "assistant", "content": "你好"}]
  ask(toolWorld, scripted(), question="再來呢", mode="assistant-jev", toolLlm=toolLlm, history=history, chooseIntent=choosing(decided()))
  assert toolLlm.calls[0][1:] == [*history, {"role": "user", "content": "再來呢"}]


def testQueryIntentBlocksProposalTools(toolWorld):
  # 對話紀錄裡有過提議時，模型可能照記憶呼叫沒給的提議工具；query 組不能因此跳出確認卡
  call = ToolReply("", [ToolCall("c1", "propose_cancel_booking", {"bookingId": toolWorld.weekly}, "")], 10, 2)
  toolLlm = toolScript(call, ToolReply("好。", [], 5, 1))
  body = ask(
    toolWorld, scripted(), question="取消週會", mode="assistant-jev", toolLlm=toolLlm, actor=toolWorld.bossActor,
    chooseIntent=choosing(decided("query")),
  )
  assert body["proposal"] is None and "這題只能用" in body["steps"][0]["error"]


def testOpenProposalAlsoAsksJevAndMergesTools(toolWorld):
  # 請假卡還開著時說「順便取消明天的週會」：卡片的請假組，再加上 Jev 判斷的改期或取消組
  toolLlm = toolScript(ToolReply("好。", [], 5, 1))
  chooser = choosing(decided("manageBooking"))
  body = ask(
    toolWorld, scripted(), question="順便取消明天的週會", mode="assistant-jev", toolLlm=toolLlm,
    openProposal="leave", chooseIntent=chooser,
  )
  assert chooser.asked == ["順便取消明天的週會"]
  merged = set(intent.intentTools["leave"]) | set(intent.intentTools["manageBooking"])
  assert set(toolLlm.toolSets[0]) == merged
  assert body["intent"] == {
    "name": "leave", "confidence": 0.9, "fallbackReason": None, "reused": True, "promptTokens": 300, "seconds": 0.1,
    "addedName": "manageBooking", "cardName": None,
  }


def testClarifyingWhileCardOpenMergesAllThree(toolWorld):
  # 請假卡還開著、上一則是在問「哪場會議？」：沿用改期或取消、保留請假卡的工具，Jev 也判斷這一句
  toolLlm = toolScript(ToolReply("好。", [], 5, 1))
  body = ask(
    toolWorld, scripted(), question="客戶簡報那場", mode="assistant-jev", toolLlm=toolLlm,
    previousIntent="manageBooking", openProposal="leave", chooseIntent=choosing(decided("booking")),
  )
  merged = set(intent.intentTools["manageBooking"]) | set(intent.intentTools["leave"]) | set(intent.intentTools["booking"])
  assert set(toolLlm.toolSets[0]) == merged
  assert (body["intent"]["name"], body["intent"]["cardName"], body["intent"]["addedName"]) == ("manageBooking", "leave", "booking")


def testCardSameAsPreviousHasNoCardName(toolWorld):
  toolLlm = toolScript(ToolReply("好。", [], 5, 1))
  body = ask(
    toolWorld, scripted(), question="改成三點", mode="assistant-jev", toolLlm=toolLlm,
    previousIntent="booking", openProposal="booking", chooseIntent=choosing(decided("booking")),
  )
  assert toolLlm.toolSets[0] == intent.intentTools["booking"]
  assert body["intent"]["cardName"] is None and body["intent"]["addedName"] is None


def testOpenProposalJevFallbackKeepsCard(toolWorld):
  toolLlm = toolScript(ToolReply("好。", [], 5, 1))
  body = ask(
    toolWorld, scripted(), question="嗯", mode="assistant-jev", toolLlm=toolLlm,
    openProposal="booking", chooseIntent=choosing(decided(None, "unavailable")),
  )
  assert toolLlm.toolSets[0] == intent.intentTools["booking"]
  assert body["intent"]["name"] == "booking" and body["intent"]["fallbackReason"] == "unavailable"


def testOpenProposalWithAllSkipsJev(toolWorld):
  # 上一輪已經是 9 個工具全給，再問 Jev 也不會多出工具
  toolLlm = toolScript(ToolReply("好。", [], 5, 1))
  ask(toolWorld, scripted(), mode="assistant-jev", toolLlm=toolLlm, previousIntent="all", openProposal="leave")
  assert toolLlm.toolSets[0] == allAssistantTools


@pytest.mark.parametrize("value", [True, "all", "foo", 1])
def testBadOpenProposal(world, value):
  # 卡片一定是某個具體的辦事意圖，所以不收 all 或布林值
  error = expectError(
    "VALIDATION", ask, world, scripted(), mode="assistant-jev", toolLlm=toolScript(), openProposal=value,
  )
  assert error.details == {"field": "openProposal"} and service.askingUserIds == set()
