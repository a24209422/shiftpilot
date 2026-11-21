from datetime import date, datetime

import pytest

from app.infra.db import openDb
from app.infra.errors import AppError
from app.modules.leave import requests
from app.modules.org import service as orgService
from app.modules.shift import service as shiftService
from tests.leave.world import makeWorld

now = datetime(2026, 11, 21, 10)


@pytest.fixture
def world(migratedUrl):
  w = makeWorld(migratedUrl)
  with openDb(migratedUrl) as conn:
    w.evening = shiftService.createShiftType(conn, w.hrActor, {
      "code": "evening", "name": "晚班", "startTime": "14:00", "endTime": "23:00", "breakStart": "18:00", "breakEnd": "19:00",
    })["id"]
    w.night = shiftService.createShiftType(conn, w.hrActor, {
      "code": "night", "name": "大夜班", "startTime": "22:00", "endTime": "06:00", "breakStart": "02:00", "breakEnd": "03:00",
    })["id"]
  return w


def roster(conn, w, employeeId, shiftTypeId):
  shiftService.createRoster(conn, w.hrActor, {
    "employeeId": employeeId, "effectiveFrom": date(2026, 11, 23),
    "days": [{"weekday": weekday, "shiftTypeId": shiftTypeId} for weekday in range(5)],
  }, now)


def leave(w, start, end, code="personal"):
  return requests.LeaveInput(w.types[code], start, end)


def testEveningShiftLeaveSubtractsBreak(world):
  with openDb(world.url) as conn:
    roster(conn, world, world.alice, world.evening)
    quote = requests.quoteRequest(conn, world.aliceActor, leave(world, datetime(2026, 11, 24, 14), datetime(2026, 11, 24, 23)))
  assert quote["hours"] == 8


def testNightShiftLeaveAcrossMidnight(world):
  with openDb(world.url) as conn:
    roster(conn, world, world.alice, world.night)
    quote = requests.quoteRequest(conn, world.aliceActor, leave(world, datetime(2026, 11, 24, 22), datetime(2026, 11, 25, 6)))
  assert quote["hours"] == 7


def testStandardHoursOutsideEveningShiftAreNotCounted(world):
  with openDb(world.url) as conn:
    roster(conn, world, world.alice, world.evening)
    quote = requests.quoteRequest(conn, world.aliceActor, leave(world, datetime(2026, 11, 24, 9), datetime(2026, 11, 24, 18)))
  # 晚班 14:00 才上班、18:00 開始休息，所以只有 14–18 這 4 小時
  assert quote["hours"] == 4


def testRestOverrideMeansNoWorkingHours(world):
  with openDb(world.url) as conn:
    shiftService.upsertOverride(conn, world.hrActor, {"employeeId": world.alice, "day": date(2026, 11, 24), "shiftTypeId": None, "note": ""}, now)
    with pytest.raises(AppError) as info:
      requests.quoteRequest(conn, world.aliceActor, leave(world, datetime(2026, 11, 24, 9), datetime(2026, 11, 24, 18)))
  assert info.value.code == "LEAVE_NO_WORKING_HOURS"


def testCalendarSegmentsFollowShifts(world):
  with openDb(world.url) as conn:
    orgService.upsertCalendarDay(conn, world.adminActor, date(2026, 11, 24), "holiday", "測試假日")
    created = requests.createRequest(conn, world.aliceActor, leave(world, datetime(2026, 11, 23, 9), datetime(2026, 11, 25, 18)), now)
    assert created["hours"] == 16
    items = requests.listCalendar(conn, world.bobActor, datetime(2026, 11, 23), datetime(2026, 11, 26))
  assert items[0]["segments"] == [
    {"startAt": "2026-11-23T09:00:00", "endAt": "2026-11-23T12:00:00"},
    {"startAt": "2026-11-23T13:00:00", "endAt": "2026-11-23T18:00:00"},
    {"startAt": "2026-11-25T09:00:00", "endAt": "2026-11-25T12:00:00"},
    {"startAt": "2026-11-25T13:00:00", "endAt": "2026-11-25T18:00:00"},
  ]


def testCalendarSegmentsAreClippedToQueryRange(world):
  with openDb(world.url) as conn:
    requests.createRequest(conn, world.aliceActor, leave(world, datetime(2026, 11, 23, 9), datetime(2026, 11, 25, 18)), now)
    items = requests.listCalendar(conn, world.bobActor, datetime(2026, 11, 24), datetime(2026, 11, 25))
  assert items[0]["segments"] == [
    {"startAt": "2026-11-24T09:00:00", "endAt": "2026-11-24T12:00:00"},
    {"startAt": "2026-11-24T13:00:00", "endAt": "2026-11-24T18:00:00"},
  ]
