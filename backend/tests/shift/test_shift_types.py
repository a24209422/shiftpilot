import pytest

from app.infra.db import openDb
from app.infra.errors import AppError
from app.modules.core.service import listAudit
from app.modules.shift import service
from tests.shift.world import makeWorld


@pytest.fixture
def world(migratedUrl):
  return makeWorld(migratedUrl)


def expectError(code, call, *args):
  with pytest.raises(AppError) as info:
    call(*args)
  assert info.value.code == code
  return info.value


def testCreatedTypeIsSerializedWithHourStrings(world):
  with openDb(world.url) as conn:
    evening = service.getShiftType(conn, world.evening)
  assert evening == {
    "id": world.evening, "code": "evening", "name": "晚班", "startTime": "14:00", "endTime": "23:00",
    "breakStart": "18:00", "breakEnd": "19:00", "isDefault": False, "isActive": True,
  }


def testCreateWritesAuditAndValidates(world):
  with openDb(world.url) as conn:
    assert listAudit(conn, "shift")[0]["action"] == "createShiftType"
    error = expectError("VALIDATION", service.createShiftType, conn, world.hrActor,
                        {"code": "half", "name": "半點班", "startTime": "08:30", "endTime": "17:30"})
    assert error.details == {"field": "startTime"}
    expectError("VALIDATION", service.createShiftType, conn, world.hrActor,
                {"code": "bad", "name": "壞班", "startTime": "9:00", "endTime": "18:00"})
    expectError("DUPLICATE", service.createShiftType, conn, world.hrActor,
                {"code": "evening", "name": "另一個晚班", "startTime": "13:00", "endTime": "22:00"})


def testListHidesInactive(world):
  with openDb(world.url) as conn:
    service.updateShiftType(conn, world.hrActor, world.night, {"isActive": False})
    assert [item["code"] for item in service.listShiftTypes(conn)] == ["standard", "evening"]
    assert [item["code"] for item in service.listShiftTypes(conn, includeInactive=True)] == ["standard", "evening", "night"]


def testTimesAreImmutable(world):
  with openDb(world.url) as conn:
    for field in ("startTime", "endTime", "breakStart", "breakEnd", "code"):
      error = expectError("SHIFT_TYPE_IMMUTABLE", service.updateShiftType, conn, world.hrActor, world.evening, {field: "10:00"})
      assert error.details == {"field": field}
    renamed = service.updateShiftType(conn, world.hrActor, world.evening, {"name": "午晚班"})
    assert renamed["name"] == "午晚班" and listAudit(conn, "shift")[0]["action"] == "updateShiftType"


def testSettingDefaultMovesItFromOldDefault(world):
  with openDb(world.url) as conn:
    service.updateShiftType(conn, world.hrActor, world.evening, {"isDefault": True})
    assert service.getShiftType(conn, world.evening)["isDefault"] is True
    assert service.getShiftType(conn, world.standard)["isDefault"] is False


def testCreateAsDefaultMovesDefault(world):
  with openDb(world.url) as conn:
    created = service.createShiftType(conn, world.hrActor, {
      "code": "late", "name": "晚一點的標準班", "startTime": "10:00", "endTime": "19:00", "breakStart": "13:00", "breakEnd": "14:00", "isDefault": True,
    })
    assert created["isDefault"] is True and service.getShiftType(conn, world.standard)["isDefault"] is False


def testDefaultCannotBeDeactivatedAndInactiveCannotBeDefault(world):
  with openDb(world.url) as conn:
    expectError("SHIFT_DEFAULT_REQUIRED", service.updateShiftType, conn, world.hrActor, world.standard, {"isActive": False})
    service.updateShiftType(conn, world.hrActor, world.night, {"isActive": False})
    expectError("SHIFT_TYPE_INACTIVE", service.updateShiftType, conn, world.hrActor, world.night, {"isDefault": True})


def testDefaultCanBeCleared(world):
  with openDb(world.url) as conn:
    cleared = service.updateShiftType(conn, world.hrActor, world.standard, {"isDefault": False})
    assert cleared["isDefault"] is False
