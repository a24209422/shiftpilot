import json
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from app.infra.db import openDb
from app.modules.booking import service as bookingService
from app.modules.booking.service import BookingInput
from app.modules.leave import requests as leaveRequests
from app.modules.qa import tools
from app.modules.qa.sandbox import collectSandboxData, openSandbox
from tests.leave.world import makeWorld

now = datetime(2026, 11, 21, 10)


def makeToolWorld(url):
  w = makeWorld(url)
  with openDb(url) as conn:
    # alice 11/24 整天請假（待核准）、11/26 10:00～11:00 在 A 會議室開週會
    leaveRequests.createRequest(conn, w.aliceActor, leaveRequests.LeaveInput(
      w.types["personal"], datetime(2026, 11, 24, 9), datetime(2026, 11, 24, 18), "搬家",
    ), now)
    room = bookingService.createResource(conn, w.adminActor, {"name": "A 會議室", "kind": "room"})["id"]
    bookingService.createBooking(conn, w.bossActor, BookingInput(
      "週會", "會議", datetime(2026, 11, 26, 10), datetime(2026, 11, 26, 11), [room], [w.alice], acknowledgeWarnings=True,
    ))
  return w


@pytest.fixture
def sandbox(migratedUrl, qaSandboxUrl):
  w = makeToolWorld(migratedUrl)
  with openDb(migratedUrl) as conn:
    data = collectSandboxData(conn, w.bobActor, date(2026, 11, 21))
  with openSandbox(qaSandboxUrl, data) as conn:
    yield SimpleNamespace(conn=conn, world=w)


def names(result):
  return sorted(row[0] for row in result.rows)


def testRunSqlRunsGuardedSql(sandbox):
  result = tools.executeTool(sandbox.conn, "run_sql", {"sql": "SELECT name FROM employees"})
  assert result.ok and result.columns == ["name"] and result.sql == "SELECT name FROM employees"
  assert names(result) == ["alice", "bob", "boss", "carol"]


def testRunSqlRejectsUnsafe(sandbox):
  result = tools.executeTool(sandbox.conn, "run_sql", {"sql": "DELETE FROM employees"})
  assert not result.ok and "SELECT" in result.error and result.sql == "DELETE FROM employees"


def testRunSqlReportsDatabaseError(sandbox):
  result = tools.executeTool(sandbox.conn, "run_sql", {"sql": "SELECT nope FROM employees"})
  assert not result.ok and "nope" in result.error


def testAvailablePeopleExcludesBusyAndOffShift(sandbox):
  result = tools.executeTool(sandbox.conn, "find_available_people", {"start": "2026-11-26 10:00", "end": "2026-11-26 11:00"})
  assert result.ok and result.columns == ["name", "department"] and result.sql is None
  # boss 是週會的主辦人、alice 是參加者，兩人都算忙
  assert names(result) == ["bob", "carol"]
  # 11/28 是週六，沒有人上班
  weekend = tools.executeTool(sandbox.conn, "find_available_people", {"start": "2026-11-28 10:00", "end": "2026-11-28 11:00"})
  assert weekend.ok and weekend.rows == []
  # 請假那天也不算有空
  leaveDay = tools.executeTool(sandbox.conn, "find_available_people", {"start": "2026-11-24 14:00", "end": "2026-11-24 15:00", "department": "工程"})
  assert "alice" not in names(leaveDay)
  other = tools.executeTool(sandbox.conn, "find_available_people", {"start": "2026-11-26 10:00", "end": "2026-11-26 11:00", "department": "業務部"})
  assert other.ok and other.rows == []


def testBusyPeriodsForEmployeeAndResource(sandbox):
  person = tools.executeTool(sandbox.conn, "get_busy_periods", {"start": "2026-11-24", "end": "2026-11-27", "employee": "alice"})
  assert person.ok and person.columns == ["who", "start_at", "end_at", "kind", "label"]
  assert {row[3] for row in person.rows} == {"meeting", "leave"}
  room = tools.executeTool(sandbox.conn, "get_busy_periods", {"start": "2026-11-26 10:30", "end": "2026-11-26 12:00", "resource": "A 會議室"})
  assert room.ok and [(row[0], row[3], row[4]) for row in room.rows] == [("A 會議室", "meeting", "週會")]
  everyone = tools.executeTool(sandbox.conn, "get_busy_periods", {"start": "2026-11-26 00:00", "end": "2026-11-27 00:00"})
  assert sorted(row[0] for row in everyone.rows) == ["alice", "boss"]


def testBusyPeriodsDoNotLeakLeaveDetails(sandbox):
  # 沙盒是 bob（一般員工）的：alice 的請假只能看到標籤，不能看到假別或事由
  result = tools.executeTool(sandbox.conn, "get_busy_periods", {"start": "2026-11-24", "end": "2026-11-25", "employee": "alice"})
  assert result.ok and result.rows
  assert {row[4] for row in result.rows} <= {"請假", "請假（待核准）"}
  assert "搬家" not in json.dumps(result.rows, ensure_ascii=False)


def testBadArgumentsReturnError(sandbox):
  for arguments in [
    None, {}, {"start": "明天下午", "end": "2026-11-24 15:00"}, {"start": "2026-11-24 15:00", "end": "2026-11-24 14:00"},
    {"start": "2026-11-24 14:00", "end": "2026-11-24 15:00", "employee": "王", "resource": "A"},
    {"start": 20261124, "end": "2026-11-24 15:00"},
  ]:
    result = tools.executeTool(sandbox.conn, "get_busy_periods", arguments)
    assert not result.ok and result.error
  assert not tools.executeTool(sandbox.conn, "run_sql", {"sql": 1}).ok
  assert not tools.executeTool(sandbox.conn, "find_available_people", {"start": "2026-11-24 14:00"}).ok


def testUnknownToolReturnsError(sandbox):
  result = tools.executeTool(sandbox.conn, "drop_tables", {})
  assert not result.ok and "drop_tables" in result.error


def testFormatForModelLimitsRows():
  result = tools.ToolResult(True, ["n"], [[index] for index in range(25)], False, None, None)
  payload = json.loads(tools.formatForModel(result))
  assert len(payload["rows"]) == 20 and payload["rowCount"] == 25 and payload["columns"] == ["n"]
  assert tools.formatForModel(tools.ToolResult(False, [], [], False, None, "壞掉")) == "錯誤：壞掉"


def testToolDefinitionsNames():
  assert [item["function"]["name"] for item in tools.toolDefinitions] == ["run_sql", "find_available_people", "get_busy_periods"]


def testTimezoneDatesAreRejected(sandbox):
  # 沙盒的時間欄位沒有時區；混用會讓比較丟 TypeError，兩邊都帶時區則會依 session 時區偏掉
  for arguments in [
    {"start": "2026-11-23T09:00+08:00", "end": "2026-11-23 10:00"},
    {"start": "2026-11-23T09:00+08:00", "end": "2026-11-23T10:00+08:00"},
  ]:
    result = tools.executeTool(sandbox.conn, "find_available_people", arguments)
    assert not result.ok and "時區" in result.error
