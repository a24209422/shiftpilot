from contextlib import nullcontext
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.modules.qa import intent, jev, sandbox, service, sqlguard
from app.modules.qa.llm import ToolCall, ToolReply
from app.modules.qa.tools import ToolResult, failed


@pytest.fixture
def ask(monkeypatch):
  conn = Mock()
  actor = SimpleNamespace(userId=1, employeeId=1)
  data = SimpleNamespace(windowStart=date(2026, 1, 1), windowEnd=date(2026, 1, 2))
  monkeypatch.setattr(service.llmModule, "listModels", lambda: [{"id": "fake", "remote": False}])
  monkeypatch.setattr(sandbox, "collectSandboxData", lambda *_: data)
  monkeypatch.setattr(sandbox, "openSandbox", lambda *_: nullcontext(conn))
  for name in ("buildSqlMessages", "buildAnswerMessages", "buildAgentMessages", "buildAssistantMessages"):
    monkeypatch.setattr(service.prompt, name, lambda *_: [])
  monkeypatch.setattr(service, "findAsker", lambda *_: None)

  def run(mode, **options):
    return service.ask(conn, actor, "問題", "fake", "unused", datetime(2026, 1, 1), mode=mode, **options)

  return run


def testPipelineEmitsEachQueryAttempt(ask, monkeypatch):
  events = []
  replies = iter(["SELECT 1", "SELECT 2", "答覆"])
  query = Mock(side_effect=[sqlguard.UnsafeSqlError("bad query"), (["值"], [[2]], False)])
  monkeypatch.setattr(sandbox, "runQuery", query)
  result = ask("pipeline", llm=lambda *_: next(replies), onEvent=events.append)
  assert result["answer"] == "答覆"
  assert events[0] == {"type": "accepted"}
  assert [(e["id"], e["stage"], e["state"]) for e in events[1:]] == [
    (1, "prepare", "running"), (1, "prepare", "done"),
    (2, "generate_query", "running"), (2, "generate_query", "done"),
    (3, "query", "running"), (3, "query", "failed"),
    (4, "generate_query", "running"), (4, "generate_query", "done"),
    (5, "query", "running"), (5, "query", "done"),
    (6, "compose", "running"), (6, "compose", "done"),
  ]


@pytest.mark.parametrize("mode", ["agent", "jev"])
def testToolsInOneReplyHaveIndividualProgress(ask, monkeypatch, mode):
  events = []
  replies = iter([
    ToolReply("", [ToolCall("one", "run_sql", {"sql": "private"}, ""), ToolCall("two", "run_sql", {}, "")], None, None),
    ToolReply("答覆", [], None, None),
  ])
  monkeypatch.setattr(service.agent.tools, "executeTool", Mock(side_effect=[failed("private"), ToolResult(True, [], [], False, None, None)]))
  result = ask(mode, toolLlm=lambda *_: next(replies), onEvent=events.append,
               chooseTool=lambda *_: jev.JevDecision(None, 0.1, "low_confidence", None, 0), jevConfigured=lambda: True)
  assert result["toolCalls"] == len(result["steps"]) == 2
  assert ("route" in result) == (mode == "jev")
  assert [(e["id"], e["state"]) for e in events if e.get("stage") == "tool"] == [
    (3 if mode == "agent" else 4, "running"), (3 if mode == "agent" else 4, "failed"),
    (4 if mode == "agent" else 5, "running"), (4 if mode == "agent" else 5, "done"),
  ]
  assert "private" not in repr(events)


def testAssistantFollowUpHasNoToolProgress(ask):
  events = []
  result = ask("assistant", toolLlm=lambda *_: ToolReply("哪一天？", [], None, None), onEvent=events.append)
  assert result["answer"] == "哪一天？"
  assert [e.get("stage") for e in events] == [None, "prepare", "prepare", "model", "model"]


def testAssistantProposalReportsPreparation(ask, monkeypatch):
  events = []
  proposal = {"kind": "booking.create"}
  monkeypatch.setattr(service.assistant, "makeExecutor", lambda *_: lambda *_: ToolResult(True, [], [], False, None, None, proposal))
  result = ask("assistant", toolLlm=lambda *_: ToolReply("", [ToolCall("one", "propose_booking", {}, "")], None, None),
               onEvent=events.append)
  assert result["proposal"] == proposal
  assert [event["state"] for event in events if event.get("stage") == "proposal"] == ["running", "done"]


def intentDecision(name):
  return intent.IntentDecision(name, 0.9, None, False, None, 0.1)


def testAssistantJevReportsIntentStep(ask):
  events = []
  ask("assistant-jev", toolLlm=lambda *_: ToolReply("哪一天？", [], None, None), onEvent=events.append,
      chooseIntent=lambda *_: intentDecision("booking"))
  assert [e.get("stage") for e in events] == [None, "prepare", "prepare", "intent", "intent", "model", "model"]


def testReusedIntentHasNoIntentStep(ask):
  # 沿用上一輪的工具組時沒有呼叫 Jev，不該顯示一個沒發生的步驟
  events = []
  chooseIntent = Mock()
  ask("assistant-jev", toolLlm=lambda *_: ToolReply("哪一天？", [], None, None), onEvent=events.append,
      previousIntent="booking", chooseIntent=chooseIntent)
  chooseIntent.assert_not_called()
  assert "intent" not in [e.get("stage") for e in events]


def testOpenProposalStillReportsIntentStep(ask):
  events = []
  ask("assistant-jev", toolLlm=lambda *_: ToolReply("好", [], None, None), onEvent=events.append,
      previousIntent="booking", openProposal="booking", chooseIntent=lambda *_: intentDecision("leave"))
  assert [e["state"] for e in events if e.get("stage") == "intent"] == ["running", "done"]


def testToolStepsCarryToolName(ask, monkeypatch):
  events = []
  proposal = {"kind": "booking.create"}
  results = iter([ToolResult(True, [], [], False, None, None), ToolResult(True, [], [], False, None, None, proposal)])
  monkeypatch.setattr(service.assistant, "makeExecutor", lambda *_: lambda *_: next(results))
  replies = iter([
    ToolReply("", [ToolCall("one", "find_available_resources", {}, "")], None, None),
    ToolReply("", [ToolCall("two", "propose_booking", {}, "")], None, None),
  ])
  ask("assistant", toolLlm=lambda *_: next(replies), onEvent=events.append)
  named = [(e["stage"], e["tool"]) for e in events if e.get("state") == "running" and "tool" in e]
  assert named == [("tool", "find_available_resources"), ("proposal", "propose_booking")]
  # 其他步驟不帶 tool 欄位
  assert all("tool" not in e for e in events if e.get("stage") in ("prepare", "model"))
