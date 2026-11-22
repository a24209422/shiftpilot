from datetime import date, datetime
from types import SimpleNamespace

import pytest

from app.infra.db import openDb
from app.modules.booking import service as bookingService
from app.modules.org import service as orgService
from app.modules.qa import proposals
from app.modules.qa.proposals import Asker, executeProposal, findAsker, formatRange
from app.modules.qa.sandbox import collectSandboxData
from tests.qa.test_qa_tools import makeToolWorld


@pytest.fixture
def world(migratedUrl):
  w = makeToolWorld(migratedUrl)
  with openDb(migratedUrl) as conn:
    w.bRoom = bookingService.createResource(conn, w.adminActor, {"name": "B 會議室", "kind": "room", "capacity": 6})["id"]
    departmentId = conn.execute("SELECT id FROM departments WHERE name = '工程部'").fetchone()["id"]
    # 名稱包含「alice」的另一個人：用來確認完全相同的名稱優先
    w.aliceChen = orgService.createEmployee(conn, w.adminActor, {
      "employeeNo": "E005", "name": "alice 陳", "departmentId": departmentId, "jobTitle": "工程師", "hiredOn": date(2025, 1, 1),
    })["id"]
    w.bobData = collectSandboxData(conn, w.bobActor, date(2026, 11, 21))
    w.aliceData = collectSandboxData(conn, w.aliceActor, date(2026, 11, 21))
  w.bobAsker = findAsker(w.bobData, w.bob)
  w.aliceAsker = findAsker(w.aliceData, w.alice)
  return w


def summaryOf(result):
  return {item["label"]: item["value"] for item in result.proposal["summary"]}


def bookingArguments(**overrides):
  return {"title": "討論", "start": "2026-11-25 14:00", "end": "2026-11-25 15:00", **overrides}


def testFormatRange():
  assert formatRange(datetime(2026, 11, 25, 14), datetime(2026, 11, 25, 15)) == "11/25（三）14:00–15:00"
  assert formatRange(datetime(2026, 11, 24, 9), datetime(2026, 11, 25, 18)) == "11/24（二）09:00 – 11/25（三）18:00"
  # 週日要是「日」
  assert formatRange(datetime(2026, 11, 22, 9), datetime(2026, 11, 22, 10)) == "11/22（日）09:00–10:00"


def testFindAsker(world):
  assert findAsker(world.bobData, world.bob) == Asker(world.bob, "bob", "工程部")
  assert findAsker(world.bobData, None) is None


def testProposalNames():
  names = [item["function"]["name"] for item in proposals.proposalDefinitions]
  assert names == [
    "propose_booking", "propose_reschedule_booking", "propose_cancel_booking", "propose_leave", "propose_withdraw_leave",
  ]
  assert proposals.proposalNames == set(names)


def testProposeBooking(world):
  result = executeProposal(world.bobData, world.bobAsker, "propose_booking", bookingArguments(participants=["alice"], resources=["B 會議室"]))
  assert result.ok and result.proposal["kind"] == "booking.create" and result.proposal["quote"] is None
  assert result.proposal["request"] == {"method": "POST", "path": "/api/booking/bookings", "body": {
    "title": "討論", "category": "會議", "startAt": "2026-11-25T14:00", "endAt": "2026-11-25T15:00",
    "resourceIds": [world.bRoom], "participantEmployeeIds": [world.alice],
  }}
  summary = summaryOf(result)
  assert summary["標題"] == "討論" and summary["參加者"] == "你、alice" and summary["時間"] == "11/25（三）14:00–15:00"
  assert summary["會議室"] == "B 會議室"


def testProposeBookingWithoutResourcesAndWithNote(world):
  result = executeProposal(world.bobData, world.bobAsker, "propose_booking", bookingArguments(note="帶筆電"))
  body = result.proposal["request"]["body"]
  assert body["note"] == "帶筆電" and body["resourceIds"] == [] and body["participantEmployeeIds"] == []
  summary = summaryOf(result)
  assert summary["參加者"] == "你" and summary["會議室"] == "不預約"


def testAmbiguousNameListsCandidates(world):
  result = executeProposal(world.bobData, world.bobAsker, "propose_booking", bookingArguments(participants=["bo"]))
  assert not result.ok and "bob" in result.error and "boss" in result.error
  assert result.proposal is None


def testUnknownNameIsError(world):
  result = executeProposal(world.bobData, world.bobAsker, "propose_booking", bookingArguments(participants=["王小明"]))
  assert not result.ok and result.error == "找不到「王小明」"


def testExactNameWins(world):
  result = executeProposal(world.bobData, world.bobAsker, "propose_booking", bookingArguments(participants=["alice"]))
  assert result.ok and result.proposal["request"]["body"]["participantEmployeeIds"] == [world.alice]


def testProposalRejectsEmptyRange(world):
  result = executeProposal(world.bobData, world.bobAsker, "propose_booking", bookingArguments(end="2026-11-25 14:00"))
  assert not result.ok and result.error == "結束時間要晚於開始時間"
  earlier = executeProposal(world.bobData, world.bobAsker, "propose_booking", bookingArguments(end="2026-11-25 13:00"))
  assert not earlier.ok and earlier.error == "結束時間要晚於開始時間"


def testRescheduleAndCancelNeedKnownBooking(world):
  times = {"start": "2026-11-27 10:00", "end": "2026-11-27 11:00"}
  unknown = executeProposal(world.bobData, world.bobAsker, "propose_reschedule_booking", {"bookingId": 99999, **times})
  assert not unknown.ok and unknown.proposal is None
  assert not executeProposal(world.bobData, world.bobAsker, "propose_cancel_booking", {"bookingId": 99999}).ok
  weekly = next(row[0] for row in world.bobData.rows["bookings"] if row[1] == "週會")
  moved = executeProposal(world.bobData, world.bobAsker, "propose_reschedule_booking", {"bookingId": weekly, **times})
  assert moved.ok and moved.proposal["kind"] == "booking.reschedule"
  assert moved.proposal["request"] == {
    "method": "PATCH", "path": f"/api/booking/bookings/{weekly}", "body": {"startAt": "2026-11-27T10:00", "endAt": "2026-11-27T11:00"},
  }
  summary = summaryOf(moved)
  assert summary["標題"] == "週會" and summary["時間"] == "11/26（四）10:00–11:00 → 11/27（五）10:00–11:00"
  cancel = executeProposal(world.bobData, world.bobAsker, "propose_cancel_booking", {"bookingId": weekly})
  assert cancel.ok and cancel.proposal["kind"] == "booking.cancel"
  assert cancel.proposal["request"] == {"method": "POST", "path": f"/api/booking/bookings/{weekly}/cancel", "body": None}
  assert summaryOf(cancel)["會議室"] == "A 會議室"


def testProposeLeaveHasQuote(world):
  typeName = next(name for typeId, name in world.bobData.leaveTypes if typeId == world.types["personal"])
  result = executeProposal(world.bobData, world.bobAsker, "propose_leave", {"leaveType": typeName, "start": "2026-11-25 09:00", "end": "2026-11-25 18:00"})
  assert result.ok and result.proposal["kind"] == "leave.create"
  request = result.proposal["request"]
  assert request["method"] == "POST" and request["path"] == "/api/leave/requests"
  assert request["body"]["leaveTypeId"] == world.types["personal"]
  assert result.proposal["quote"] == {"path": "/api/leave/requests/quote", "body": request["body"]}
  summary = summaryOf(result)
  assert summary["假別"] == typeName and summary["原因"] == "（未填）" and summary["時間"] == "11/25（三）09:00–18:00"


def testWithdrawOnlyOwnPending(world):
  requestId = world.bobData.rows["leave_requests"][0][0]
  denied = executeProposal(world.bobData, world.bobAsker, "propose_withdraw_leave", {"requestId": requestId})
  assert not denied.ok and denied.error == "只能撤回自己待核准的申請"
  allowed = executeProposal(world.aliceData, world.aliceAsker, "propose_withdraw_leave", {"requestId": requestId})
  assert allowed.ok and allowed.proposal["kind"] == "leave.withdraw"
  assert allowed.proposal["request"] == {"method": "POST", "path": f"/api/leave/requests/{requestId}/withdraw", "body": None}
  assert summaryOf(allowed)["原因"] == "搬家"


def testNoEmployeeCannotBookOrLeave(world):
  for name, arguments in [
    ("propose_booking", bookingArguments()),
    ("propose_leave", {"leaveType": "事假", "start": "2026-11-25 09:00", "end": "2026-11-25 18:00"}),
  ]:
    result = executeProposal(world.bobData, None, name, arguments)
    assert not result.ok and result.error == "你的帳號沒有員工資料，不能預約或請假"


def testBadArgumentsAreErrors(world):
  data, asker = world.bobData, world.bobAsker
  assert not executeProposal(data, asker, "propose_nothing", {}).ok
  assert not executeProposal(data, asker, "propose_booking", None).ok
  assert not executeProposal(data, asker, "propose_booking", bookingArguments(participants="alice")).ok
  assert not executeProposal(data, asker, "propose_cancel_booking", {"bookingId": "abc"}).ok
