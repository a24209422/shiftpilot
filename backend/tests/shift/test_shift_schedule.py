from datetime import date, datetime

import pytest

from app.infra.db import openDb
from app.infra.errors import AppError
from app.modules.org import service as orgService
from app.modules.shift import service
from tests.shift.world import insertOverride, insertRoster, makeWorld


@pytest.fixture
def world(migratedUrl):
  return makeWorld(migratedUrl)


def dt(day, hour):
  return datetime(2026, 11, day, hour)


def days(rows, employeeId):
  return {row["day"]: row for row in rows if row["employeeId"] == employeeId}


# 2026-11-23 是星期一
def testDefaultScheduleForWeek(world):
  with openDb(world.url) as conn:
    rows = service.getSchedule(conn, [world.alice], date(2026, 11, 23), date(2026, 11, 29))
  assert len(rows) == 7
  assert rows[0] == {
    "employeeId": world.alice, "day": "2026-11-23", "source": "default", "shiftTypeId": world.standard, "shiftName": "標準班",
    "startAt": "2026-11-23T09:00:00", "endAt": "2026-11-23T18:00:00", "breakStartAt": "2026-11-23T12:00:00",
    "breakEndAt": "2026-11-23T13:00:00", "holidayName": None, "overrideNote": None,
  }
  assert [row["source"] for row in rows] == ["default"] * 5 + ["off", "off"]


def testAllActiveEmployeesWhenNoIdsGiven(world):
  with openDb(world.url) as conn:
    orgService.updateEmployee(conn, world.adminActor, world.bob, {"isActive": False})
    rows = service.getSchedule(conn, None, date(2026, 11, 23), date(2026, 11, 23))
  assert [row["employeeId"] for row in rows] == [world.boss, world.alice, world.carol]


def testCalendarHolidayAndMakeupDay(world):
  with openDb(world.url) as conn:
    orgService.upsertCalendarDay(conn, world.adminActor, date(2026, 11, 25), "holiday", "測試假日")
    orgService.upsertCalendarDay(conn, world.adminActor, date(2026, 11, 28), "makeup_workday", "補班")
    byDay = days(service.getSchedule(conn, [world.alice], date(2026, 11, 23), date(2026, 11, 29)), world.alice)
  assert byDay["2026-11-25"]["source"] == "holiday" and byDay["2026-11-25"]["holidayName"] == "測試假日"
  assert byDay["2026-11-28"]["source"] == "default"


def testRosterSwitchesOnEffectiveDay(world):
  with openDb(world.url) as conn:
    insertRoster(conn, world, world.alice, date(2026, 11, 25), {0: world.evening, 1: world.evening, 2: world.evening, 3: world.evening, 4: world.evening})
    byDay = days(service.getSchedule(conn, [world.alice], date(2026, 11, 23), date(2026, 11, 29)), world.alice)
  assert byDay["2026-11-24"]["source"] == "default"
  assert byDay["2026-11-25"]["source"] == "roster" and byDay["2026-11-25"]["shiftName"] == "晚班"
  assert byDay["2026-11-25"]["startAt"] == "2026-11-25T14:00:00"
  assert byDay["2026-11-28"]["source"] == "roster" and byDay["2026-11-28"]["shiftTypeId"] is None


def testOverridesBeatEverything(world):
  with openDb(world.url) as conn:
    orgService.upsertCalendarDay(conn, world.adminActor, date(2026, 11, 25), "holiday", "測試假日")
    insertOverride(conn, world, world.alice, date(2026, 11, 24), None, "補休")
    insertOverride(conn, world, world.alice, date(2026, 11, 25), world.evening, "值班")
    byDay = days(service.getSchedule(conn, [world.alice], date(2026, 11, 23), date(2026, 11, 29)), world.alice)
  assert byDay["2026-11-24"]["source"] == "override" and byDay["2026-11-24"]["shiftTypeId"] is None
  assert byDay["2026-11-24"]["overrideNote"] == "補休"
  assert byDay["2026-11-25"]["shiftName"] == "晚班" and byDay["2026-11-25"]["holidayName"] == "測試假日"


def testLeftEmployeeKeepsHistory(world):
  with openDb(world.url) as conn:
    orgService.updateEmployee(conn, world.adminActor, world.bob, {"isActive": False, "leftOn": date(2026, 11, 25)})
    byDay = days(service.getSchedule(conn, [world.bob], date(2026, 11, 23), date(2026, 11, 29)), world.bob)
  assert byDay["2026-11-25"]["source"] == "default" and byDay["2026-11-26"]["source"] == "inactive"


def testNoDefaultShiftMeansOff(world):
  with openDb(world.url) as conn:
    service.updateShiftType(conn, world.hrActor, world.standard, {"isDefault": False})
    rows = service.getSchedule(conn, [world.alice], date(2026, 11, 23), date(2026, 11, 23))
  assert rows[0]["source"] == "off"


def testScheduleRangeLimit(world):
  with openDb(world.url) as conn:
    with pytest.raises(AppError) as info:
      service.getSchedule(conn, None, date(2026, 11, 1), date(2026, 12, 2))
    assert info.value.code == "VALIDATION"
    assert len(service.getSchedule(conn, [world.alice], date(2026, 11, 1), date(2026, 12, 1))) == 31


def testWorkWindowsIncludePreviousNightShift(world):
  with openDb(world.url) as conn:
    insertRoster(conn, world, world.alice, date(2026, 11, 23), {0: world.night, 1: world.night})
    windows = service.workWindows(conn, [world.alice, world.bob], dt(24, 0), dt(24, 23))
  assert windows[world.alice] == [(dt(24, 0), dt(24, 2)), (dt(24, 3), dt(24, 6)), (dt(24, 22), datetime(2026, 11, 24, 23))]
  assert windows[world.bob] == [(dt(24, 9), dt(24, 12)), (dt(24, 13), dt(24, 18))]


def testShiftSpansKeepWholeShift(world):
  with openDb(world.url) as conn:
    spans = service.shiftSpans(conn, [world.alice], dt(24, 10), dt(24, 11))
  assert [(day.day, day.startAt, day.endAt) for day in spans[world.alice]] == [
    (date(2026, 11, 23), dt(23, 9), dt(23, 18)), (date(2026, 11, 24), dt(24, 9), dt(24, 18)),
  ]
