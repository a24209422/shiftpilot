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
    w.bossData = collectSandboxData(conn, w.bossActor, date(2026, 11, 21))
  w.bossAsker = findAsker(w.bossData, w.boss)
  w.bobAsker = findAsker(w.bobData, w.bob)
  w.aliceAsker = findAsker(w.aliceData, w.alice)
  return w


def summaryOf(result):
  return {item["label"]: item["value"] for item in result.proposal["summary"]}


def bookingArguments(**overrides):
  return {"title": "討論", "start": "2026-11-25 14:00", "end": "2026-11-25 15:00", **overrides}


def testFormatRange():
  assert formatRange(datetime(2026, 11, 25, 14), datetime(2026, 11, 25, 15)) == "11/25（三） 14:00–15:00"
  assert formatRange(datetime(2026, 11, 24, 9), datetime(2026, 11, 25, 18)) == "11/24（二） 09:00 – 11/25（三） 18:00"
  # 週日要是「日」
  assert formatRange(datetime(2026, 11, 22, 9), datetime(2026, 11, 22, 10)) == "11/22（日） 09:00–10:00"


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
  assert summary["標題"] == "討論" and summary["參加者"] == "你、alice" and summary["時間"] == "11/25（三） 14:00–15:00"
  assert summary["資源"] == "B 會議室"


def testProposeBookingWithoutResourcesAndWithNote(world):
  result = executeProposal(world.bobData, world.bobAsker, "propose_booking", bookingArguments(note="帶筆電"))
  body = result.proposal["request"]["body"]
  assert body["note"] == "帶筆電" and body["resourceIds"] == [] and body["participantEmployeeIds"] == []
  summary = summaryOf(result)
  assert summary["參加者"] == "你" and summary["資源"] == "不預約"


def testBookingSummaryShowsCategoryAndNote(world):
  # 確認卡要列出 body 送出的每一項，使用者才知道按下確認會寫入什麼
  withNote = summaryOf(executeProposal(world.bobData, world.bobAsker, "propose_booking", bookingArguments(note="帶筆電")))
  assert withNote["類別"] == "會議" and withNote["備註"] == "帶筆電"
  withoutNote = summaryOf(executeProposal(world.bobData, world.bobAsker, "propose_booking", bookingArguments()))
  assert withoutNote["類別"] == "會議" and "備註" not in withoutNote


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
  # 週會是 boss 建的
  weekly = next(row[0] for row in world.bossData.rows["bookings"] if row[1] == "週會")
  moved = executeProposal(world.bossData, world.bossAsker, "propose_reschedule_booking", {"bookingId": weekly, **times})
  assert moved.ok and moved.proposal["kind"] == "booking.reschedule"
  assert moved.proposal["request"] == {
    "method": "PATCH", "path": f"/api/booking/bookings/{weekly}", "body": {"startAt": "2026-11-27T10:00", "endAt": "2026-11-27T11:00"},
  }
  summary = summaryOf(moved)
  assert summary["標題"] == "週會" and summary["時間"] == "11/26（四） 10:00–11:00 → 11/27（五） 10:00–11:00"
  cancel = executeProposal(world.bossData, world.bossAsker, "propose_cancel_booking", {"bookingId": weekly})
  assert cancel.ok and cancel.proposal["kind"] == "booking.cancel"
  assert cancel.proposal["request"] == {"method": "POST", "path": f"/api/booking/bookings/{weekly}/cancel", "body": None}
  assert summaryOf(cancel)["資源"] == "A 會議室"


def testProposeLeaveHasQuote(world):
  typeName = next(name for typeId, name in world.bobData.leaveTypes if typeId == world.types["personal"])
  result = executeProposal(world.bobData, world.bobAsker, "propose_leave", {"leaveType": typeName, "start": "2026-11-25 09:00", "end": "2026-11-25 18:00"})
  assert result.ok and result.proposal["kind"] == "leave.create"
  request = result.proposal["request"]
  assert request["method"] == "POST" and request["path"] == "/api/leave/requests"
  assert request["body"]["leaveTypeId"] == world.types["personal"]
  assert result.proposal["quote"] == {"path": "/api/leave/requests/quote", "body": request["body"]}
  summary = summaryOf(result)
  assert summary["假別"] == typeName and summary["原因"] == "（未填）" and summary["時間"] == "11/25（三） 09:00–18:00"


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


# 同名員工：只回姓名的話，模型怎麼回答都會再對到同樣兩位，要能用部門、員工編號或 #id 指定

@pytest.fixture
def twins(migratedUrl):
  w = makeToolWorld(migratedUrl)
  with openDb(migratedUrl) as conn:
    engineering = conn.execute("SELECT id FROM departments WHERE name = '工程部'").fetchone()["id"]
    sales = orgService.createDepartment(conn, w.adminActor, "業務部")["id"]
    w.chenEngineering = orgService.createEmployee(conn, w.adminActor, {
      "employeeNo": "E101", "name": "陳志明", "departmentId": engineering, "jobTitle": "工程師", "hiredOn": date(2025, 1, 1),
    })["id"]
    w.chenSales = orgService.createEmployee(conn, w.adminActor, {
      "employeeNo": "E102", "name": "陳志明", "departmentId": sales, "jobTitle": "業務", "hiredOn": date(2025, 1, 1),
    })["id"]
    w.bigRoom = bookingService.createResource(conn, w.adminActor, {"name": "會議室(大)", "kind": "room", "location": "3F"})["id"]
    w.data = collectSandboxData(conn, w.bobActor, date(2026, 11, 21))
  w.asker = findAsker(w.data, w.bob)
  return w


def participantsOf(world, *names):
  return executeProposal(world.data, world.asker, "propose_booking", bookingArguments(participants=list(names)))


def testSameNameAsksWithDepartmentAndEmployeeNo(twins):
  result = participantsOf(twins, "陳志明")
  assert not result.ok
  assert f"陳志明（工程部，E101，#{twins.chenEngineering}）" in result.error
  assert f"陳志明（業務部，E102，#{twins.chenSales}）" in result.error


@pytest.mark.parametrize("text,expected", [
  ("陳志明（業務部）", "chenSales"),
  ("陳志明(E101)", "chenEngineering"),
  # 模型把反問裡的整串提示照抄回來也要能用
  ("陳志明（業務部，E102，#{chenSales}）", "chenSales"),
])
def testSameNameResolvedByQualifier(twins, text, expected):
  result = participantsOf(twins, text.format(chenSales=twins.chenSales))
  assert result.ok and result.proposal["request"]["body"]["participantEmployeeIds"] == [getattr(twins, expected)]


def testSameNameResolvedById(twins):
  result = participantsOf(twins, f"#{twins.chenSales}")
  assert result.ok and result.proposal["request"]["body"]["participantEmployeeIds"] == [twins.chenSales]
  assert not participantsOf(twins, "#99999").ok


def testQualifierThatMatchesNobodyIsError(twins):
  result = participantsOf(twins, "陳志明（人資部）")
  assert not result.ok and result.error == "找不到「陳志明」（人資部）"


def testNameWithParenthesesStillMatchesExactly(twins):
  result = executeProposal(twins.data, twins.asker, "propose_booking", bookingArguments(resources=["會議室(大)"]))
  assert result.ok and result.proposal["request"]["body"]["resourceIds"] == [twins.bigRoom]
  located = executeProposal(twins.data, twins.asker, "propose_booking", bookingArguments(resources=["會議室（3F）"]))
  assert located.ok and located.proposal["request"]["body"]["resourceIds"] == [twins.bigRoom]


@pytest.mark.parametrize("value", ["²", "①", "3²", " "])
def testNonDecimalDigitsAreArgumentErrors(world, value):
  # isdigit() 會收這些字元但 int() 轉不了，以前會變成 500
  result = executeProposal(world.bobData, world.bobAsker, "propose_cancel_booking", {"bookingId": value})
  assert not result.ok and result.error == "參數 bookingId 要是整數"


def testRescheduleAndCancelNeedPermission(world):
  # bob 不是週會的建立者，也沒有 booking.writeAny：提議時就擋下，不用等確認後才 403
  weekly = next(row[0] for row in world.bobData.rows["bookings"] if row[1] == "週會")
  times = {"start": "2026-11-27 10:00", "end": "2026-11-27 11:00"}
  moved = executeProposal(world.bobData, world.bobAsker, "propose_reschedule_booking", {"bookingId": weekly, **times})
  assert not moved.ok and moved.error == f"只有建立者或有權限的人可以改期會議 #{weekly}"
  cancel = executeProposal(world.bobData, world.bobAsker, "propose_cancel_booking", {"bookingId": weekly})
  assert not cancel.ok and cancel.error == f"只有建立者或有權限的人可以取消會議 #{weekly}"


def testHrCanProposeForAnyBooking(world, migratedUrl):
  with openDb(migratedUrl) as conn:
    hrData = collectSandboxData(conn, world.hrActor, date(2026, 11, 21))
  weekly = next(row[0] for row in hrData.rows["bookings"] if row[1] == "週會")
  assert weekly in hrData.modifiableBookingIds
  assert executeProposal(hrData, findAsker(hrData, world.carol), "propose_cancel_booking", {"bookingId": weekly}).ok


def testSecondsAreDroppedBeforeComparing(world):
  # 同一分鐘內的起訖捨掉秒數後是零長度，要在提議時就擋下
  sameMinute = executeProposal(world.bobData, world.bobAsker, "propose_booking", bookingArguments(start="2026-11-25 10:00:10", end="2026-11-25 10:00:50"))
  assert not sameMinute.ok and sameMinute.error == "結束時間要晚於開始時間"
  result = executeProposal(world.bobData, world.bobAsker, "propose_booking", bookingArguments(start="2026-11-25 10:00:30", end="2026-11-25 11:00:59"))
  body = result.proposal["request"]["body"]
  assert body["startAt"] == "2026-11-25T10:00" and body["endAt"] == "2026-11-25T11:00"
  assert summaryOf(result)["時間"] == "11/25（三） 10:00–11:00"


def testResourceLabelIsGeneric(world, migratedUrl):
  with openDb(migratedUrl) as conn:
    car = bookingService.createResource(conn, world.adminActor, {"name": "公務車 1 號", "kind": "vehicle"})["id"]
    data = collectSandboxData(conn, world.bobActor, date(2026, 11, 21))
  result = executeProposal(data, findAsker(data, world.bob), "propose_booking", bookingArguments(resources=["公務車 1 號"]))
  summary = summaryOf(result)
  assert result.proposal["request"]["body"]["resourceIds"] == [car]
  assert summary["資源"] == "公務車 1 號" and "會議室" not in summary
