from datetime import date, datetime

import pytest

from app.infra.db import openDb
from app.modules.booking import service as bookingService
from app.modules.booking.service import BookingInput
from app.modules.leave import requests as leaveRequests
from app.modules.qa.sandbox import collectSandboxData, dataWindow
from app.modules.shift import service as shiftService
from tests.leave.world import makeWorld

today = date(2026, 11, 21)
now = datetime(2026, 11, 21, 10)


@pytest.fixture
def world(migratedUrl):
  w = makeWorld(migratedUrl)
  with openDb(migratedUrl) as conn:
    w.aliceLeave = leaveRequests.createRequest(conn, w.aliceActor, leaveRequests.LeaveInput(
      w.types["personal"], datetime(2026, 11, 24, 9), datetime(2026, 11, 24, 18), "搬家",
    ), now)["id"]
    bobLeave = leaveRequests.createRequest(conn, w.bobActor, leaveRequests.LeaveInput(
      w.types["sick"], datetime(2026, 11, 25, 9), datetime(2026, 11, 25, 18), "看醫生",
    ), now)["id"]
    leaveRequests.rejectRequest(conn, w.hrActor, bobLeave, "不行", now)
    w.bobRejected = bobLeave
    room = bookingService.createResource(conn, w.adminActor, {"name": "A 會議室", "kind": "room"})["id"]
    w.meeting = bookingService.createBooking(conn, w.bossActor, BookingInput(
      "週會", "會議", datetime(2026, 11, 26, 10), datetime(2026, 11, 26, 11), [room], [w.alice], acknowledgeWarnings=True,
    ))["id"]
    bookingService.createBooking(conn, w.bossActor, BookingInput(
      "遠期會議", "會議", datetime(2027, 6, 1, 10), datetime(2027, 6, 1, 11), [room], [], acknowledgeWarnings=True,
    ))
  return w


def collect(w, actor):
  with openDb(w.url) as conn:
    return collectSandboxData(conn, actor, today)


def leaveRows(data):
  # 欄位順序：id, employee_id, leave_type, start_at, end_at, hours, status, reason
  return {row[0]: row for row in data.rows["leave_requests"]}


def testWindowIsNinetyDaysEachWay():
  assert dataWindow(today) == (date(2026, 8, 23), date(2027, 2, 19))


def testOtherEmployeeSeesLeaveWithoutTypeOrReason(world):
  rows = leaveRows(collect(world, world.bobActor))
  alice = rows[world.aliceLeave]
  assert alice[1] == world.alice and alice[2] is None and alice[7] is None and alice[6] == "pending"


def testOthersRejectedRequestsAreAbsentButOwnArePresent(world):
  assert world.bobRejected not in leaveRows(collect(world, world.aliceActor))
  own = leaveRows(collect(world, world.bobActor))[world.bobRejected]
  assert own[2] == "病假" and own[6] == "rejected" and own[7] == "看醫生"


def testManagerAndHrSeeDetails(world):
  assert leaveRows(collect(world, world.bossActor))[world.aliceLeave][2] == "事假"
  hrRows = leaveRows(collect(world, world.hrActor))
  assert hrRows[world.aliceLeave][7] == "搬家" and hrRows[world.bobRejected][2] == "病假"


def testDayShiftsMatchShiftService(world):
  data = collect(world, world.bobActor)
  shifts = {(row[0], row[1]): row for row in data.rows["day_shifts"]}
  with openDb(world.url) as conn:
    expected = shiftService.getSchedule(conn, [world.alice], date(2026, 11, 24), date(2026, 11, 24))[0]
  row = shifts[(world.alice, date(2026, 11, 24))]
  assert row[2] == expected["shiftName"] and row[3].isoformat() == expected["startAt"] and row[7] == expected["source"]
  assert len(data.rows["day_shifts"]) == 4 * 181


def testBusyPeriodsHaveMeetingsAndLeaveSegments(world):
  busy = collect(world, world.bobActor).rows["busy_periods"]
  assert (world.alice, datetime(2026, 11, 26, 10), datetime(2026, 11, 26, 11), "meeting", "週會") in busy
  assert (world.alice, datetime(2026, 11, 24, 9), datetime(2026, 11, 24, 12), "leave", "請假（待核准）") in busy
  assert (world.alice, datetime(2026, 11, 24, 13), datetime(2026, 11, 24, 18), "leave", "請假（待核准）") in busy
  assert not any(row[0] == world.bob and row[3] == "leave" for row in busy)


def testOutOfWindowBookingsAreExcluded(world):
  titles = [row[1] for row in collect(world, world.bobActor).rows["bookings"]]
  assert "週會" in titles and "遠期會議" not in titles


def testVocabularyListsNames(world):
  vocabulary = collect(world, world.bobActor).vocabulary
  assert "工程部" in vocabulary["departments"] and "標準班" in vocabulary["shifts"]
  assert "事假" in vocabulary["leaveTypes"] and "A 會議室" in vocabulary["resources"]
