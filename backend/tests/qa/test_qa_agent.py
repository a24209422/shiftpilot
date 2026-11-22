from datetime import date, datetime
from types import SimpleNamespace

import pytest

from app.infra.db import openDb
from app.modules.qa import agent, prompt
from app.modules.qa.llm import ToolCall, ToolReply
from app.modules.qa.sandbox import collectSandboxData, openSandbox
from tests.qa.test_qa_tools import makeToolWorld

now = datetime(2026, 11, 21, 10)


@pytest.fixture
def sandbox(migratedUrl, qaSandboxUrl):
  w = makeToolWorld(migratedUrl)
  with openDb(migratedUrl) as conn:
    data = collectSandboxData(conn, w.bobActor, date(2026, 11, 21))
  with openSandbox(qaSandboxUrl, data) as conn:
    yield SimpleNamespace(conn=conn, data=data)


def call(name, arguments, callId="c1"):
  return ToolCall(callId, name, arguments, "")


def reply(*calls, content="", tokens=(None, None)):
  return ToolReply(content, list(calls), tokens[0], tokens[1])


def scriptedTools(*replies):
  calls, toolSets = [], []

  def fake(model, messages, tools):
    # 存副本：agent 之後會繼續往同一份對話加訊息
    calls.append(list(messages))
    toolSets.append([item["function"]["name"] for item in tools])
    return replies[len(calls) - 1]

  fake.calls = calls
  fake.toolSets = toolSets
  return fake


def run(sandbox, fake):
  return agent.runAgent(sandbox.conn, fake, "qwen2.5:3b", [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}])


def testTwoStepsThenAnswer(sandbox):
  fake = scriptedTools(
    reply(call("run_sql", {"sql": "SELECT nope FROM employees"}, "a")),
    reply(call("run_sql", {"sql": "SELECT name FROM employees"}, "b")),
    reply(content="有四位員工。"),
  )
  outcome = run(sandbox, fake)
  assert outcome.answer == "有四位員工。" and outcome.toolCalls == 2 and outcome.result.ok and not outcome.exhausted
  assert [step["error"] is None for step in outcome.steps] == [False, True]
  assert outcome.steps[1] == {"tool": "run_sql", "arguments": {"sql": "SELECT name FROM employees"}, "rowCount": 4, "error": None}
  second = fake.calls[1]
  assert second[-2]["role"] == "assistant" and second[-2]["toolCalls"][0].id == "a"
  assert second[-1]["role"] == "tool" and second[-1]["toolCallId"] == "a" and second[-1]["content"].startswith("錯誤：")


def testResultIsLastSuccessfulTool(sandbox):
  fake = scriptedTools(
    reply(call("run_sql", {"sql": "SELECT name FROM employees"})),
    reply(call("run_sql", {"sql": "SELECT nope FROM employees"})),
    reply(content="好。"),
  )
  outcome = run(sandbox, fake)
  assert outcome.result.sql == "SELECT name FROM employees" and len(outcome.result.rows) == 4


def testToolCallsInOneTurnRespectCap(sandbox):
  many = [call("run_sql", {"sql": "SELECT 1 AS n"}, f"c{index}") for index in range(6)]
  fake = scriptedTools(reply(*many))
  outcome = run(sandbox, fake)
  assert outcome.toolCalls == 4 and outcome.exhausted and len(fake.calls) == 1 and len(outcome.steps) == 4
  assert outcome.answer == "查到 1 筆資料。"


def testExhaustedAcrossTurns(sandbox):
  fake = scriptedTools(*[reply(call("run_sql", {"sql": "SELECT 1 AS n"})) for _ in range(5)])
  outcome = run(sandbox, fake)
  assert len(fake.calls) == 4 and outcome.exhausted and outcome.toolCalls == 4


def testDirectAnswerWithoutToolsFails(sandbox):
  fake = scriptedTools(reply(content='<tool_call>{"name": "run_sql"}</tool_call>'))
  outcome = run(sandbox, fake)
  assert outcome.result is None and outcome.toolCalls == 0 and outcome.steps == []


def testThinkIsStrippedAndEmptyAnswerFallsBack(sandbox):
  fake = scriptedTools(reply(call("run_sql", {"sql": "SELECT name FROM employees"})), reply(content="<think>想一下</think>"))
  assert run(sandbox, fake).answer == "查到 4 筆資料。"
  fake = scriptedTools(reply(call("run_sql", {"sql": "SELECT name FROM employees"})), reply(content="<think>想</think>四位。"))
  assert run(sandbox, fake).answer == "四位。"


def testTokensAreSummed(sandbox):
  fake = scriptedTools(reply(call("run_sql", {"sql": "SELECT 1 AS n"}), tokens=(100, 10)), reply(content="一。", tokens=(None, 5)))
  outcome = run(sandbox, fake)
  assert (outcome.promptTokens, outcome.completionTokens) == (100, 15)


def testAgentPromptHasToolsGuideWithoutFewShots(sandbox):
  messages = prompt.buildAgentMessages("誰有空？", sandbox.data, now)
  system = messages[0]["content"]
  assert "find_available_people" in system and "get_busy_periods" in system and "日期參考" in system
  assert "busy_periods" in system and "工程部" in system
  assert [message["role"] for message in messages] == ["system", "user"] and messages[1]["content"] == "誰有空？"


def testRawToolCallTextAfterSuccessFallsBack(sandbox):
  # Ollama 解析模板失敗時，tool call 會變成純文字；不能把這段原文當回答顯示
  fake = scriptedTools(
    reply(call("run_sql", {"sql": "SELECT name FROM employees"})),
    reply(content='<tool_call>{"name": "run_sql", "arguments": {}}</tool_call>'),
  )
  assert run(sandbox, fake).answer == "查到 4 筆資料。"


def testAllowedToolsLimitsDefinitions(sandbox):
  fake = scriptedTools(reply(content="好"))
  agent.runAgent(sandbox.conn, fake, "m", [{"role": "user", "content": "q"}], allowedTools=["find_available_people"])
  assert fake.toolSets == [["find_available_people"]]


def testAllowedToolsNoneKeepsAll(sandbox):
  fake = scriptedTools(reply(content="好"))
  run(sandbox, fake)
  assert fake.toolSets == [["run_sql", "find_available_people", "get_busy_periods"]]


def testRejectsToolOutsideAllowed(sandbox):
  fake = scriptedTools(
    reply(call("run_sql", {"sql": "SELECT name FROM employees"}, "a")),
    reply(content="沒辦法。"),
  )
  outcome = agent.runAgent(
    sandbox.conn, fake, "m", [{"role": "user", "content": "q"}], allowedTools=["find_available_people"],
  )
  assert outcome.toolCalls == 1 and outcome.result is None
  assert outcome.steps[0]["error"] == "這題只能用 find_available_people" and outcome.steps[0]["rowCount"] is None
  # 沒執行：模型收到的是錯誤文字，不是資料列
  assert fake.calls[1][-1]["content"] == "錯誤：這題只能用 find_available_people"
