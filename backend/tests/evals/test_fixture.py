from datetime import date

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


def testFixtureIsDeterministic():
  def snapshot():
    with openEvalWorld() as w:
      data = sandboxFor(w, "hr")
      return {name: sorted(map(repr, rows)) for name, rows in data.rows.items()}

  assert snapshot() == snapshot()
