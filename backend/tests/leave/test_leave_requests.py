from datetime import date, datetime

import pytest

from app.infra.db import openDb
from app.infra.errors import AppError
from app.modules.booking import service as bookingService
from app.modules.booking.service import BookingInput
from app.modules.core.service import listAudit
from app.modules.leave import requests, service
from app.modules.org import service as orgService
from tests.leave.world import makeWorld

now = datetime(2026, 11, 21, 10)


@pytest.fixture
def world(migratedUrl):
  return makeWorld(migratedUrl)


def expectError(code, call, *args, **kwargs):
  with pytest.raises(AppError) as info:
    call(*args, **kwargs)
  assert info.value.code == code
  return info.value


def leave(w, code="personal", start=datetime(2026, 11, 24, 9), end=datetime(2026, 11, 24, 18), **extra):
  return requests.LeaveInput(w.types[code], start, end, **extra)


def testQuoteReturnsHoursAndRemainingWithoutSaving(world):
  with openDb(world.url) as conn:
    quote = requests.quoteRequest(conn, world.aliceActor, leave(world, "annual"))
    assert quote == {"hours": 8, "remainingAfter": 48, "conflicts": []}
    assert requests.listRequests(conn, world.aliceActor, "mine") == []


def testCreateRequestStoresSnapshotAndAudits(world):
  with openDb(world.url) as conn:
    created = requests.createRequest(conn, world.aliceActor, leave(world, reason=" 搬家 "), now)
    assert created["status"] == "pending" and created["hours"] == 8 and created["reason"] == "搬家"
    assert created["employeeName"] == "alice" and created["leaveTypeName"] == "事假" and created["startAt"] == "2026-11-24T09:00:00"
    assert created["createdBy"] == world.aliceActor.userId and created["decidedBy"] is None
    assert listAudit(conn, "leave")[0]["action"] == "createLeaveRequest"


def testCreateRequestRejectsWhenQuotaExceeded(world):
  with openDb(world.url) as conn:
    # 56 小時的特休：先用掉 48 小時（6 個工作天），再請 16 小時要擋下
    requests.createRequest(conn, world.aliceActor, leave(world, "annual", datetime(2026, 11, 2, 9), datetime(2026, 11, 9, 18)), now)
    error = expectError(
      "LEAVE_QUOTA_EXCEEDED", requests.createRequest, conn, world.aliceActor,
      leave(world, "annual", datetime(2026, 11, 24, 9), datetime(2026, 11, 25, 18)), now,
    )
    assert error.details == {"remainingHours": 8}
    requests.createRequest(conn, world.aliceActor, leave(world, "annual", datetime(2026, 11, 24, 9), datetime(2026, 11, 24, 18)), now)


def testUnlimitedTypeHasNoQuotaCheck(world):
  with openDb(world.url) as conn:
    created = requests.createRequest(conn, world.aliceActor, leave(world, "official", datetime(2026, 11, 2, 9), datetime(2026, 11, 27, 18)), now)
    assert created["hours"] == 160


def testValidationErrors(world):
  with openDb(world.url) as conn:
    expectError("NO_EMPLOYEE", requests.createRequest, conn, world.adminActor, leave(world), now)
    expectError("VALIDATION", requests.createRequest, conn, world.aliceActor, leave(world, end=datetime(2026, 11, 24, 9)), now)
    error = expectError("VALIDATION", requests.createRequest, conn, world.aliceActor, leave(world, start=datetime(2026, 11, 24, 9, 30)), now)
    assert error.details == {"field": "startAt"}
    expectError("LEAVE_NO_WORKING_HOURS", requests.createRequest, conn, world.aliceActor,
                leave(world, start=datetime(2026, 11, 28, 9), end=datetime(2026, 11, 28, 18)), now)
    expectError("LEAVE_CROSSES_PERIOD", requests.createRequest, conn, world.aliceActor,
                leave(world, start=datetime(2026, 12, 31, 9), end=datetime(2027, 1, 4, 18)), now)
    expectError("LEAVE_NOT_ELIGIBLE", requests.createRequest, conn, world.aliceActor,
                leave(world, start=datetime(2024, 12, 2, 9), end=datetime(2024, 12, 2, 18)), now)


def testHugeRangeRejectedByPeriodCheckBeforeCountingHours(world):
  with openDb(world.url) as conn:
    # 年度檢查要先於逐日算時數，否則這個區間會跑幾百萬天的迴圈
    expectError("LEAVE_CROSSES_PERIOD", requests.quoteRequest, conn, world.aliceActor,
                leave(world, start=datetime(2026, 11, 24, 9), end=datetime(9999, 12, 31, 9)))


def testInactiveTypeAndLeftEmployeeRejected(world):
  with openDb(world.url) as conn:
    service.updateLeaveType(conn, world.hrActor, world.types["personal"], {"isActive": False})
    error = expectError("VALIDATION", requests.createRequest, conn, world.aliceActor, leave(world), now)
    assert error.details == {"field": "leaveTypeId"}
    orgService.updateEmployee(conn, world.adminActor, world.bob, {"isActive": False, "leftOn": date(2026, 11, 20)})
    expectError("LEAVE_NOT_ELIGIBLE", requests.createRequest, conn, world.bobActor, leave(world, "sick"), now)


def testPastDatesAllowed(world):
  with openDb(world.url) as conn:
    created = requests.createRequest(conn, world.aliceActor, leave(world, "sick", datetime(2026, 11, 2, 9), datetime(2026, 11, 2, 18)), now)
    assert created["status"] == "pending"


def testHolidayFromCalendarIsExcluded(world):
  with openDb(world.url) as conn:
    orgService.upsertCalendarDay(conn, world.adminActor, date(2026, 11, 25), "holiday", "測試假日")
    quote = requests.quoteRequest(conn, world.aliceActor, leave(world, start=datetime(2026, 11, 24, 9), end=datetime(2026, 11, 26, 18)))
    assert quote["hours"] == 16


def testOverlappingRequestRejected(world):
  with openDb(world.url) as conn:
    first = requests.createRequest(conn, world.aliceActor, leave(world), now)
    error = expectError("LEAVE_OVERLAP", requests.createRequest, conn, world.aliceActor,
                        leave(world, "sick", datetime(2026, 11, 24, 13), datetime(2026, 11, 24, 15)), now)
    assert [item["id"] for item in error.details["overlaps"]] == [first["id"]]


def testMeetingConflictWarnsUntilAcknowledged(world):
  with openDb(world.url) as conn:
    room = bookingService.createResource(conn, world.adminActor, {"name": "A 會議室", "kind": "room"})["id"]
    meeting = bookingService.createBooking(conn, world.bossActor, BookingInput(
      "週會", "會議", datetime(2026, 11, 24, 10), datetime(2026, 11, 24, 11), [room], [world.alice],
    ))
    quote = requests.quoteRequest(conn, world.aliceActor, leave(world))
    assert quote["conflicts"] == [{"bookingId": meeting["id"], "title": "週會", "startAt": "2026-11-24T10:00:00", "endAt": "2026-11-24T11:00:00"}]
    error = expectError("MEETING_CONFLICT", requests.createRequest, conn, world.aliceActor, leave(world), now)
    assert error.status == 409 and error.details["conflicts"] == quote["conflicts"]
    created = requests.createRequest(conn, world.aliceActor, leave(world, acknowledgeWarnings=True), now)
    assert created["status"] == "pending"


def testListScopes(world):
  with openDb(world.url) as conn:
    aliceRequest = requests.createRequest(conn, world.aliceActor, leave(world), now)
    bobRequest = requests.createRequest(conn, world.bobActor, leave(world), now)
    assert [item["id"] for item in requests.listRequests(conn, world.aliceActor, "mine")] == [aliceRequest["id"]]
    # boss 是 alice 的主管；bob 沒有主管，只有人資看得到
    assert [item["id"] for item in requests.listRequests(conn, world.bossActor, "toApprove")] == [aliceRequest["id"]]
    assert {item["id"] for item in requests.listRequests(conn, world.hrActor, "toApprove")} == {bobRequest["id"]}
    assert len(requests.listRequests(conn, world.hrActor, "all")) == 2
    expectError("FORBIDDEN", requests.listRequests, conn, world.bossActor, "all")
    expectError("VALIDATION", requests.listRequests, conn, world.bossActor, "everything")


def testToApproveFallsBackToHrWhenManagerLeft(world):
  with openDb(world.url) as conn:
    aliceRequest = requests.createRequest(conn, world.aliceActor, leave(world), now)
    orgService.updateEmployee(conn, world.adminActor, world.boss, {"isActive": False, "leftOn": date(2026, 11, 20)})
    assert [item["id"] for item in requests.listRequests(conn, world.hrActor, "toApprove")] == [aliceRequest["id"]]


def testGetRequestVisibility(world):
  with openDb(world.url) as conn:
    created = requests.createRequest(conn, world.aliceActor, leave(world), now)
    assert requests.getRequest(conn, world.bossActor, created["id"])["id"] == created["id"]
    expectError("FORBIDDEN", requests.getRequest, conn, world.bobActor, created["id"])
    expectError("NOT_FOUND", requests.getRequest, conn, world.hrActor, 9999)
