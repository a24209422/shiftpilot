from collections import Counter
from datetime import date, datetime

import pytest

from app.infra.db import openDb
from app.modules.qa.sandbox import collectSandboxData
from evals.fixture import askerNames, fixedNow, openEvalWorld


@pytest.fixture(scope="module")
def world():
  with openEvalWorld() as w:
    yield w


def sandboxFor(world, asker):
  with openDb(world.url) as conn:
    return collectSandboxData(conn, world.actors[asker], fixedNow.date())


def testAskersExistAndHaveEmployees(world):
  assert set(world.actors) == set(askerNames)
  data = sandboxFor(world, "employee")
  namesById = {row[0]: row[2] for row in data.rows["employees"]}
  for asker, name in askerNames.items():
    assert namesById[world.actors[asker].employeeId] == name
  assert world.actors["hr"].role == "hr" and world.actors["manager"].role == "manager"


def testDepartedEmployeeIsNotListed(world):
  names = [row[2] for row in sandboxFor(world, "hr").rows["employees"]]
  assert "周志明" not in names and len(names) == 11


def testEveryLeaveStatusIsVisibleToHr(world):
  statuses = {row[6] for row in sandboxFor(world, "hr").rows["leave_requests"]}
  assert statuses == {"pending", "approved", "rejected", "withdrawn", "cancelled"}


def testOutOfWindowLeaveIsAbsent(world):
  starts = [row[3].date() for row in sandboxFor(world, "hr").rows["leave_requests"]]
  assert date(2026, 6, 1) not in starts and min(starts) >= date(2026, 8, 19)


def testEmployeeSeesOthersLeaveWithoutDetails(world):
  data = sandboxFor(world, "employee")
  requesterId = world.actors["requester"].employeeId
  others = [row for row in data.rows["leave_requests"] if row[1] == requesterId]
  assert others and all(row[2] is None and row[7] is None for row in others)
  assert {row[6] for row in others} <= {"pending", "approved"}


def testManagerSeesSubordinateLeaveType(world):
  data = sandboxFor(world, "manager")
  requesterId = world.actors["requester"].employeeId
  types = {row[2] for row in data.rows["leave_requests"] if row[1] == requesterId}
  assert {"事假", "特休", "病假"} <= types


def testCancelledBookingIsAbsentAndMultiResourceMeetingExists(world):
  data = sandboxFor(world, "employee")
  titles = [row[1] for row in data.rows["bookings"]]
  assert "預算討論" not in titles and "需求訪談" in titles
  interviewId = next(row[0] for row in data.rows["bookings"] if row[1] == "需求訪談")
  assert len([row for row in data.rows["booking_resources"] if row[0] == interviewId]) == 2


def testShiftsHolidayAndOvernight(world):
  data = sandboxFor(world, "employee")
  assert (date(2026, 11, 27), "holiday", "公司創立紀念日") in data.rows["calendar_days"]
  assert (date(2026, 12, 5), "makeup_workday", "補班日") in data.rows["calendar_days"]
  employeeIds = {row[2]: row[0] for row in data.rows["employees"]}
  shifts = {(row[0], row[1]): row for row in data.rows["day_shifts"]}
  huang = shifts[(employeeIds["黃志強"], date(2026, 11, 17))]
  assert huang[2] == "晚班"
  night = shifts[(employeeIds["鄭家豪"], date(2026, 11, 17))]
  assert night[2] == "大夜班" and night[4].date() == date(2026, 11, 18)
  assert shifts[(employeeIds["林小美"], date(2026, 11, 18))][2] is None
  assert shifts[(employeeIds["李佳穎"], date(2026, 11, 21))][2] == "標準班"
  assert shifts[(employeeIds["林小美"], date(2026, 11, 27))][2] is None


def leaveOf(world, name, start):
  data = sandboxFor(world, "hr")
  employeeIds = {row[2]: row[0] for row in data.rows["employees"]}
  return next(row for row in data.rows["leave_requests"] if row[1] == employeeIds[name] and row[3] == start)


def testPartialDayLeaveHours(world):
  assert leaveOf(world, "吳宗翰", datetime(2026, 11, 10, 9))[5] == 2
  assert leaveOf(world, "劉怡君", datetime(2026, 11, 9, 7))[5] == 4
  assert leaveOf(world, "許淑芬", datetime(2026, 11, 13, 9))[5] == 6
  assert leaveOf(world, "李佳穎", datetime(2026, 11, 12, 14))[5] == 2
  assert all(leaveOf(world, name, start)[6] == "approved" for name, start in [
    ("吳宗翰", datetime(2026, 11, 10, 9)), ("劉怡君", datetime(2026, 11, 9, 7)), ("許淑芬", datetime(2026, 11, 13, 9)),
  ])


def testMidnightCrossingLeave(world):
  row = leaveOf(world, "鄭家豪", datetime(2026, 11, 18, 22))
  assert row[4] == datetime(2026, 11, 19, 7) and row[6] == "pending"


def testMultiDayLeaveSkipsWeekendAndHoliday(world):
  # 11-26 ～ 11-30 跨週末與 11-27 假日，只算 11-26 與 11-30 兩個工作天
  assert leaveOf(world, "林小美", datetime(2026, 11, 26, 9))[5] == 16
  assert leaveOf(world, "陳大文", datetime(2026, 11, 2, 9))[5] == 24


def testPastApprovedLeaveInLastWeek(world):
  pastWeek = [
    row for row in sandboxFor(world, "hr").rows["leave_requests"]
    if row[6] == "approved" and date(2026, 11, 9) <= row[3].date() <= date(2026, 11, 15)
  ]
  assert len(pastWeek) >= 2


def testEmployeeAskerOwnsApprovedAndPendingLeave(world):
  data = sandboxFor(world, "employee")
  ownId = world.actors["employee"].employeeId
  assert {row[6] for row in data.rows["leave_requests"] if row[1] == ownId} >= {"approved", "pending"}


def testOverrideWorkOnRestDay(world):
  data = sandboxFor(world, "employee")
  employeeIds = {row[2]: row[0] for row in data.rows["employees"]}
  saturday = next(row for row in data.rows["day_shifts"] if row[0] == employeeIds["李佳穎"] and row[1] == date(2026, 11, 21))
  assert saturday[2] == "標準班" and saturday[7] == "override"


def testPastHolidayInWindow(world):
  assert (date(2026, 10, 9), "holiday", "國慶日") in sandboxFor(world, "employee").rows["calendar_days"]


def testBookingTitlesAreUniqueAndAttendanceHasClearTop(world):
  data = sandboxFor(world, "employee")
  titles = [row[1] for row in data.rows["bookings"]]
  assert len(titles) == len(set(titles))
  counts = Counter(row[1] for row in data.rows["booking_participants"])
  ranked = counts.most_common()
  assert ranked[0][1] > ranked[1][1] > ranked[2][1]
  assert ranked[0][0] == next(row[0] for row in data.rows["employees"] if row[2] == "陳大文")
  assert len(counts) < 11


def testNoOneIsBookedOutsideShiftOrDuringLeave(world):
  data = sandboxFor(world, "hr")
  windows: dict[int, list[tuple[datetime, datetime]]] = {}
  for employeeId, _day, shiftName, startAt, endAt, breakStart, breakEnd, _source in data.rows["day_shifts"]:
    if shiftName is None:
      continue
    # 休息時段不算上班，會議要整段落在休息前或休息後
    segments = [(startAt, breakStart), (breakEnd, endAt)] if breakStart else [(startAt, endAt)]
    windows.setdefault(employeeId, []).extend(segments)
  bookings = {row[0]: row for row in data.rows["bookings"]}
  for bookingId, employeeId, _role in data.rows["booking_participants"]:
    startAt, endAt = bookings[bookingId][3], bookings[bookingId][4]
    assert any(a <= startAt and endAt <= b for a, b in windows.get(employeeId, [])), bookings[bookingId][1]
    for leave in data.rows["leave_requests"]:
      if leave[1] == employeeId and leave[6] in ("pending", "approved"):
        assert not (leave[3] < endAt and leave[4] > startAt), bookings[bookingId][1]


def testFixtureIsDeterministic():
  def snapshot():
    with openEvalWorld() as w:
      return {
        asker: {name: list(map(repr, rows)) for name, rows in sandboxFor(w, asker).rows.items()}
        for asker in askerNames
      }

  assert snapshot() == snapshot()
