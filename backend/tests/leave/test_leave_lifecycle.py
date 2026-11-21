from datetime import datetime

import pytest

from app.infra.db import openDb
from app.infra.errors import AppError
from app.infra.registry import clearUnavailabilityProviders, registerUnavailabilityProvider
from app.modules.booking import service as bookingService
from app.modules.booking.service import BookingInput
from app.modules.core.service import listAudit
from app.modules.leave import requests, service
from tests.leave.world import makeWorld

now = datetime(2026, 11, 21, 10)


@pytest.fixture
def world(migratedUrl):
  return makeWorld(migratedUrl)


@pytest.fixture(autouse=True)
def resetProviders():
  clearUnavailabilityProviders()
  yield
  clearUnavailabilityProviders()


def expectError(code, call, *args, **kwargs):
  with pytest.raises(AppError) as info:
    call(*args, **kwargs)
  assert info.value.code == code
  return info.value


def submit(conn, w, actor, code="personal", start=datetime(2026, 11, 24, 9), end=datetime(2026, 11, 24, 18)):
  return requests.createRequest(conn, actor, requests.LeaveInput(w.types[code], start, end), now)


def testManagerApprovesWithNote(world):
  with openDb(world.url) as conn:
    created = submit(conn, world, world.aliceActor)
    approved = requests.approveRequest(conn, world.bossActor, created["id"], "好好休息", now)
    assert approved["status"] == "approved" and approved["decidedBy"] == world.bossActor.userId
    assert approved["decidedByName"] == "boss" and approved["decisionNote"] == "好好休息" and approved["decidedAt"] == "2026-11-21T10:00:00"
    assert listAudit(conn, "leave")[0]["action"] == "approveLeaveRequest"


def testOnlyDirectManagerOrHrCanApprove(world):
  with openDb(world.url) as conn:
    created = submit(conn, world, world.aliceActor)
    expectError("FORBIDDEN", requests.approveRequest, conn, world.bobActor, created["id"], None, now)
    expectError("FORBIDDEN", requests.approveRequest, conn, world.aliceActor, created["id"], None, now)
    assert requests.approveRequest(conn, world.hrActor, created["id"], None, now)["status"] == "approved"


def testHrCannotApproveOwnRequest(world):
  with openDb(world.url) as conn:
    created = submit(conn, world, world.hrActor)
    error = expectError("FORBIDDEN", requests.approveRequest, conn, world.hrActor, created["id"], None, now)
    assert "自己" in error.message


def testApproveRechecksQuota(world):
  with openDb(world.url) as conn:
    created = submit(conn, world, world.aliceActor, "annual", datetime(2026, 11, 2, 9), datetime(2026, 11, 10, 18))
    assert created["hours"] == 56
    service.createAdjustment(conn, world.hrActor, {
      "employeeId": world.alice, "leaveTypeId": world.types["annual"], "periodStart": datetime(2026, 1, 1).date(), "hours": -8, "reason": "更正",
    }, now)
    error = expectError("LEAVE_QUOTA_EXCEEDED", requests.approveRequest, conn, world.bossActor, created["id"], None, now)
    assert error.details == {"remainingHours": -8}


def testRejectNeedsNote(world):
  with openDb(world.url) as conn:
    created = submit(conn, world, world.aliceActor)
    expectError("VALIDATION", requests.rejectRequest, conn, world.bossActor, created["id"], "  ", now)
    rejected = requests.rejectRequest(conn, world.bossActor, created["id"], "那週要上線", now)
    assert rejected["status"] == "rejected" and rejected["decisionNote"] == "那週要上線"


def testWithdrawOnlyByOwnerWhilePending(world):
  with openDb(world.url) as conn:
    created = submit(conn, world, world.aliceActor)
    expectError("FORBIDDEN", requests.withdrawRequest, conn, world.bossActor, created["id"], now)
    withdrawn = requests.withdrawRequest(conn, world.aliceActor, created["id"], now)
    assert withdrawn["status"] == "withdrawn" and withdrawn["cancelledBy"] == world.aliceActor.userId
    expectError("LEAVE_INVALID_STATE", requests.withdrawRequest, conn, world.aliceActor, created["id"], now)
    expectError("LEAVE_INVALID_STATE", requests.approveRequest, conn, world.bossActor, created["id"], None, now)


def testOwnerCancelsApprovedBeforeStartOnly(world):
  with openDb(world.url) as conn:
    created = submit(conn, world, world.aliceActor)
    expectError("LEAVE_INVALID_STATE", requests.cancelRequest, conn, world.aliceActor, created["id"], now)
    requests.approveRequest(conn, world.bossActor, created["id"], None, now)
    expectError("FORBIDDEN", requests.cancelRequest, conn, world.aliceActor, created["id"], datetime(2026, 11, 24, 9))
    expectError("FORBIDDEN", requests.cancelRequest, conn, world.bobActor, created["id"], now)
    cancelled = requests.cancelRequest(conn, world.aliceActor, created["id"], now)
    assert cancelled["status"] == "cancelled" and cancelled["cancelledAt"] == "2026-11-21T10:00:00"


def testHrCancelsStartedLeave(world):
  with openDb(world.url) as conn:
    created = submit(conn, world, world.aliceActor)
    requests.approveRequest(conn, world.bossActor, created["id"], None, now)
    assert requests.cancelRequest(conn, world.hrActor, created["id"], datetime(2026, 11, 24, 12))["status"] == "cancelled"


def testCancelledRequestFreesQuotaAndTime(world):
  with openDb(world.url) as conn:
    created = submit(conn, world, world.aliceActor, "annual")
    requests.withdrawRequest(conn, world.aliceActor, created["id"], now)
    again = submit(conn, world, world.aliceActor, "annual")
    assert again["status"] == "pending"


def testCalendarHidesLeaveTypeFromOthers(world):
  with openDb(world.url) as conn:
    created = submit(conn, world, world.aliceActor)
    start, end = datetime(2026, 11, 24), datetime(2026, 11, 25)
    assert requests.listCalendar(conn, world.aliceActor, start, end)[0]["leaveTypeName"] == "事假"
    assert requests.listCalendar(conn, world.bossActor, start, end)[0]["leaveTypeName"] == "事假"
    assert requests.listCalendar(conn, world.hrActor, start, end)[0]["leaveTypeName"] == "事假"
    assert requests.listCalendar(conn, world.bobActor, start, end) == [{
      "id": created["id"], "employeeId": world.alice, "startAt": "2026-11-24T09:00:00", "endAt": "2026-11-24T18:00:00",
      "status": "pending", "leaveTypeName": None,
      "segments": [
        {"startAt": "2026-11-24T09:00:00", "endAt": "2026-11-24T12:00:00"},
        {"startAt": "2026-11-24T13:00:00", "endAt": "2026-11-24T18:00:00"},
      ],
    }]
    expectError("VALIDATION", requests.listCalendar, conn, world.bobActor, start, datetime(2027, 1, 1))


def testUnavailabilityShowsInBookingWarnings(world):
  registerUnavailabilityProvider("leave", requests.findUnavailability)
  with openDb(world.url) as conn:
    created = submit(conn, world, world.aliceActor)
    room = bookingService.createResource(conn, world.adminActor, {"name": "A 會議室", "kind": "room"})["id"]
    data = BookingInput("週會", "會議", datetime(2026, 11, 24, 10), datetime(2026, 11, 24, 11), [room], [world.alice])
    error = expectError("PARTICIPANT_CONFLICT", bookingService.createBooking, conn, world.bossActor, data)
    assert error.details["conflicts"] == [{
      "name": "alice", "employeeId": world.alice, "reason": "請假（待核准）", "startAt": "2026-11-24T09:00:00", "endAt": "2026-11-24T18:00:00",
    }]
    requests.approveRequest(conn, world.bossActor, created["id"], None, now)
    error = expectError("PARTICIPANT_CONFLICT", bookingService.createBooking, conn, world.bossActor, data)
    assert error.details["conflicts"][0]["reason"] == "請假"
