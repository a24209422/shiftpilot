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


def parseTime(value):
  # listCalendar 已經把時間轉成 ISO 字串，和沙盒的 datetime 比較前要先轉回來
  return value if isinstance(value, datetime) else datetime.fromisoformat(value)


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


def testOutOfWindowLeaveIsExcludedFromLeaveAndBusy(world):
  with openDb(world.url) as conn:
    leaveRequests.createRequest(conn, world.aliceActor, leaveRequests.LeaveInput(
      world.types["personal"], datetime(2027, 6, 1, 9), datetime(2027, 6, 1, 18), "遠期",
    ), now)
  data = collect(world, world.hrActor)
  assert not any(row[3].year == 2027 and row[3].month == 6 for row in data.rows["leave_requests"])
  assert not any(row[1].year == 2027 and row[1].month == 6 for row in data.rows["busy_periods"])


def testBusyLeaveSegmentsMatchCalendarSegmentsAcrossWeekend(world):
  # 2026-11-27 是週五、11-30 是週一：週末不上班，片段要和時間軸一致
  with openDb(world.url) as conn:
    leaveRequests.createRequest(conn, world.aliceActor, leaveRequests.LeaveInput(
      world.types["personal"], datetime(2026, 11, 27, 9), datetime(2026, 11, 30, 18), "連假",
    ), now)
    calendar = leaveRequests.listCalendar(conn, world.hrActor, datetime(2026, 11, 20), datetime(2026, 12, 20))
  expected = sorted(
    (world.alice, parseTime(segment["startAt"]), parseTime(segment["endAt"]))
    for item in calendar if item["employeeId"] == world.alice
    for segment in item["segments"]
  )
  busy = collect(world, world.hrActor).rows["busy_periods"]
  actual = sorted((row[0], row[1], row[2]) for row in busy if row[0] == world.alice and row[3] == "leave")
  assert actual == expected
  assert any(start.date() == date(2026, 11, 27) for _, start, _ in actual) and any(start.date() == date(2026, 11, 30) for _, start, _ in actual)
  assert not any(start.date() in (date(2026, 11, 28), date(2026, 11, 29)) for _, start, _ in actual)


def testOutOfWindowBookingsAreExcluded(world):
  titles = [row[1] for row in collect(world, world.bobActor).rows["bookings"]]
  assert "週會" in titles and "遠期會議" not in titles


def testVocabularyListsNames(world):
  vocabulary = collect(world, world.bobActor).vocabulary
  assert "工程部" in vocabulary["departments"] and "標準班" in vocabulary["shifts"]
  assert "事假" in vocabulary["leaveTypes"] and "A 會議室" in vocabulary["resources"]


def testLeaveTypesCarryIds(world):
  data = collect(world, world.bobActor)
  assert {name for _, name in data.leaveTypes} == set(data.vocabulary["leaveTypes"])
  assert all(typeId in world.types.values() for typeId, _ in data.leaveTypes)
  # 假別 id 只給助理提案用，不能進沙盒資料表
  assert "leaveTypes" not in data.rows
