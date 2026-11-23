from datetime import date
from types import SimpleNamespace

import pytest

from app.infra.db import openDb
from app.modules.booking import service as bookingService
from app.modules.qa import assistant, tools
from app.modules.qa.proposals import findAsker
from app.modules.qa.sandbox import collectSandboxData, openSandbox
from tests.qa.test_qa_tools import makeToolWorld


@pytest.fixture
def sandbox(migratedUrl, qaSandboxUrl):
  w = makeToolWorld(migratedUrl)
  with openDb(migratedUrl) as conn:
    bookingService.createResource(conn, w.adminActor, {"name": "B 會議室", "kind": "room", "capacity": 6})
    data = collectSandboxData(conn, w.bobActor, date(2026, 11, 21))
  with openSandbox(qaSandboxUrl, data) as conn:
    yield SimpleNamespace(conn=conn, world=w, data=data, asker=findAsker(data, w.bob))


slot = {"start": "2026-11-26 10:30", "end": "2026-11-26 11:00"}


def testAvailableResourcesExcludeBooked(sandbox):
  # A 會議室 10:00～11:00 有週會，所以只剩 B
  result = assistant.executeAssistantTool(sandbox.conn, "find_available_resources", {**slot, "kind": "room"})
  assert result.ok and result.columns == ["name", "kind", "location", "capacity"]
  assert [row[0] for row in result.rows] == ["B 會議室"]


def testAvailableResourcesCapacity(sandbox):
  result = assistant.executeAssistantTool(sandbox.conn, "find_available_resources", {**slot, "kind": "room", "minCapacity": 10})
  assert result.ok and result.rows == []


def testAvailableResourcesRejectsBadArguments(sandbox):
  assert not assistant.executeAssistantTool(sandbox.conn, "find_available_resources", {**slot, "kind": "boat"}).ok
  assert not assistant.executeAssistantTool(sandbox.conn, "find_available_resources", {**slot, "minCapacity": "大"}).ok


def testExecutorRoutesProposalAndQuery(sandbox):
  execute = assistant.makeExecutor(sandbox.data, sandbox.asker)
  query = execute(sandbox.conn, "run_sql", {"sql": "SELECT name FROM employees"})
  assert query.ok and query.rows
  # 週會是 boss 建的：有走到提議工具，才會收到權限的錯誤
  proposal = execute(sandbox.conn, "propose_cancel_booking", {"bookingId": 1})
  assert proposal.error == "只有建立者或有權限的人可以取消會議 #1"
  free = execute(sandbox.conn, "find_available_resources", {**slot, "kind": "room"})
  assert free.ok and len(free.rows) == 1
  assert not execute(sandbox.conn, "find_available_resources", None).ok
  assert execute(sandbox.conn, "propose_cancel_booking", "x").error == "參數不是合法的 JSON 物件"


def testAgentToolsUnchanged():
  assert [d["function"]["name"] for d in tools.toolDefinitions] == ["run_sql", "find_available_people", "get_busy_periods"]
  assert "find_available_resources" not in tools.handlers
  names = [d["function"]["name"] for d in assistant.assistantToolDefinitions]
  assert names[:3] == ["run_sql", "find_available_people", "get_busy_periods"] and names[3] == "find_available_resources"
  assert assistant.maxAssistantToolCalls == 6
