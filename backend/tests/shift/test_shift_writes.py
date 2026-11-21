from datetime import date, datetime

import pytest

from app.infra.db import openDb
from app.infra.errors import AppError
from app.modules.core.service import listAudit
from app.modules.shift import service
from tests.shift.world import makeWorld

now = datetime(2026, 11, 21, 10)
today = date(2026, 11, 21)


@pytest.fixture
def world(migratedUrl):
  return makeWorld(migratedUrl)


def expectError(code, call, *args):
  with pytest.raises(AppError) as info:
    call(*args)
  assert info.value.code == code
  return info.value


def rosterData(w, employeeId, effectiveFrom=date(2026, 11, 23), days=None):
  return {"employeeId": employeeId, "effectiveFrom": effectiveFrom,
          "days": days if days is not None else [{"weekday": weekday, "shiftTypeId": w.evening} for weekday in range(5)]}


def testWhoCanSchedule(world):
  with openDb(world.url) as conn:
    service.requireCanSchedule(conn, world.bossActor, world.alice)
    service.requireCanSchedule(conn, world.hrActor, world.bob)
    service.requireCanSchedule(conn, world.adminActor, world.boss)
    expectError("FORBIDDEN", service.requireCanSchedule, conn, world.bobActor, world.alice)
    expectError("FORBIDDEN", service.requireCanSchedule, conn, world.bossActor, world.boss)
    expectError("FORBIDDEN", service.requireCanSchedule, conn, world.aliceActor, world.alice)
    expectError("NOT_FOUND", service.requireCanSchedule, conn, world.hrActor, 9999)


def testCreateRosterAffectsSchedule(world):
  with openDb(world.url) as conn:
    roster = service.createRoster(conn, world.bossActor, rosterData(world, world.alice), now)
    assert roster["effectiveFrom"] == "2026-11-23" and roster["createdBy"] == world.bossActor.userId
    assert roster["days"][0] == {"weekday": 0, "shiftTypeId": world.evening, "shiftName": "晚班"} and len(roster["days"]) == 5
    assert service.listRosters(conn, world.alice) == [roster]
    assert listAudit(conn, "shift")[0]["action"] == "createShiftRoster"
    rows = service.getSchedule(conn, [world.alice], date(2026, 11, 23), date(2026, 11, 23))
  assert rows[0]["source"] == "roster" and rows[0]["shiftName"] == "晚班"


def testRosterValidation(world):
  with openDb(world.url) as conn:
    error = expectError("ROSTER_BEFORE_HIRE", service.createRoster, conn, world.hrActor, rosterData(world, world.alice, date(2024, 12, 30)), now)
    assert error.details == {"field": "effectiveFrom"}
    expectError("VALIDATION", service.createRoster, conn, world.hrActor,
                rosterData(world, world.alice, days=[{"weekday": 0, "shiftTypeId": world.evening}, {"weekday": 0, "shiftTypeId": world.night}]), now)
    expectError("VALIDATION", service.createRoster, conn, world.hrActor,
                rosterData(world, world.alice, days=[{"weekday": 7, "shiftTypeId": world.evening}]), now)
    service.updateShiftType(conn, world.hrActor, world.night, {"isActive": False})
    expectError("SHIFT_TYPE_INACTIVE", service.createRoster, conn, world.hrActor,
                rosterData(world, world.alice, days=[{"weekday": 0, "shiftTypeId": world.night}]), now)
    service.createRoster(conn, world.hrActor, rosterData(world, world.alice), now)
    expectError("DUPLICATE", service.createRoster, conn, world.hrActor, rosterData(world, world.alice), now)
    expectError("FORBIDDEN", service.createRoster, conn, world.bobActor, rosterData(world, world.alice), now)


def testEmptyRosterMeansAllRest(world):
  with openDb(world.url) as conn:
    service.createRoster(conn, world.hrActor, rosterData(world, world.alice, days=[]), now)
    rows = service.getSchedule(conn, [world.alice], date(2026, 11, 23), date(2026, 11, 23))
  assert rows[0]["source"] == "roster" and rows[0]["shiftTypeId"] is None


def testOnlyFutureRostersCanBeDeleted(world):
  with openDb(world.url) as conn:
    past = service.createRoster(conn, world.hrActor, rosterData(world, world.alice, date(2026, 11, 21)), now)
    future = service.createRoster(conn, world.hrActor, rosterData(world, world.alice, date(2026, 11, 23)), now)
    expectError("ROSTER_ALREADY_EFFECTIVE", service.deleteRoster, conn, world.hrActor, past["id"], today)
    expectError("FORBIDDEN", service.deleteRoster, conn, world.bobActor, future["id"], today)
    service.deleteRoster(conn, world.bossActor, future["id"], today)
    assert [item["id"] for item in service.listRosters(conn, world.alice)] == [past["id"]]
    assert listAudit(conn, "shift")[0]["action"] == "deleteShiftRoster"
    expectError("NOT_FOUND", service.deleteRoster, conn, world.hrActor, future["id"], today)


def testUpsertOverrideCreatesThenUpdates(world):
  with openDb(world.url) as conn:
    created = service.upsertOverride(conn, world.bossActor, {"employeeId": world.alice, "day": date(2026, 11, 24), "shiftTypeId": None, "note": " 補休 "}, now)
    assert created["shiftTypeId"] is None and created["shiftName"] is None and created["note"] == "補休"
    later = datetime(2026, 11, 22, 9)
    updated = service.upsertOverride(conn, world.hrActor, {"employeeId": world.alice, "day": date(2026, 11, 24), "shiftTypeId": world.evening, "note": ""}, later)
    assert updated["id"] == created["id"] and updated["shiftName"] == "晚班"
    assert updated["createdBy"] == world.bossActor.userId and updated["updatedBy"] == world.hrActor.userId
    audit = listAudit(conn, "shift")[0]
    assert audit["action"] == "upsertShiftOverride" and audit["before"]["note"] == "補休"
    assert service.listOverrides(conn, world.alice, date(2026, 11, 23), date(2026, 11, 29)) == [updated]


def testOverrideValidationAndPermission(world):
  with openDb(world.url) as conn:
    service.updateShiftType(conn, world.hrActor, world.night, {"isActive": False})
    error = expectError("SHIFT_TYPE_INACTIVE", service.upsertOverride, conn, world.hrActor,
                        {"employeeId": world.alice, "day": date(2026, 11, 24), "shiftTypeId": world.night, "note": ""}, now)
    assert error.details == {"field": "shiftTypeId"}
    expectError("FORBIDDEN", service.upsertOverride, conn, world.bobActor,
                {"employeeId": world.alice, "day": date(2026, 11, 24), "shiftTypeId": None, "note": ""}, now)


def testDeleteOverride(world):
  with openDb(world.url) as conn:
    service.upsertOverride(conn, world.hrActor, {"employeeId": world.alice, "day": date(2026, 11, 24), "shiftTypeId": None, "note": ""}, now)
    expectError("FORBIDDEN", service.deleteOverride, conn, world.bobActor, world.alice, date(2026, 11, 24))
    service.deleteOverride(conn, world.bossActor, world.alice, date(2026, 11, 24))
    assert listAudit(conn, "shift")[0]["action"] == "deleteShiftOverride"
    expectError("NOT_FOUND", service.deleteOverride, conn, world.hrActor, world.alice, date(2026, 11, 24))
