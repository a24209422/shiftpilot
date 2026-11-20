from datetime import datetime

import pytest

from app.infra.actor import Actor
from app.infra.db import openDb
from app.infra.errors import AppError
from app.infra.registry import clearUnavailabilityProviders, registerUnavailabilityProvider
from app.modules.booking import service
from app.modules.booking.service import BookingInput
from app.modules.core.service import listAudit
from app.modules.org import service as orgService
from tests.helpers import insertActor


def at(hour, minute=0, day=24):
  return datetime(2026, 11, day, hour, minute)


@pytest.fixture(autouse=True)
def resetProviders():
  clearUnavailabilityProviders()
  yield
  clearUnavailabilityProviders()


class World:
  pass


@pytest.fixture
def world(migratedUrl):
  w = World()
  w.url = migratedUrl
  with openDb(migratedUrl) as conn:
    setup = insertActor(conn, "admin", "setup@example.com")
    departmentId = orgService.createDepartment(conn, setup, "工程部")["id"]
    for name, number in (("alice", "E001"), ("bob", "E002"), ("carol", "E003")):
      employee = orgService.createEmployee(
        conn, setup, {"employeeNo": number, "name": name, "departmentId": departmentId, "jobTitle": "工程師", "hiredOn": datetime(2025, 1, 1).date()}
      )
      setattr(w, name, employee["id"])
    w.aliceActor = insertActor(conn, "employee", "alice@example.com", w.alice)
    w.bobActor = insertActor(conn, "employee", "bob@example.com", w.bob)
    w.hrActor = insertActor(conn, "hr", "carol@example.com", w.carol)
    w.adminActor = setup
    w.room1 = service.createResource(conn, setup, {"name": "A 會議室", "kind": "room", "capacity": 8})["id"]
    w.room2 = service.createResource(conn, setup, {"name": "B 會議室", "kind": "room"})["id"]
  return w


def inputFor(w, **overrides):
  values = {
    "title": "週會", "category": "會議", "startAt": at(10), "endAt": at(11),
    "resourceIds": [w.room1], "participantEmployeeIds": [],
  }
  values.update(overrides)
  return BookingInput(**values)


def expectError(code, call, *args, **kwargs):
  with pytest.raises(AppError) as info:
    call(*args, **kwargs)
  assert info.value.code == code
  return info.value


def testCreateBookingStoresResourcesAndParticipants(world):
  with openDb(world.url) as conn:
    booking = service.createBooking(conn, world.aliceActor, inputFor(world, participantEmployeeIds=[world.bob], note="帶筆電"))
    assert booking["status"] == "confirmed" and booking["startAt"] == "2026-11-24T10:00:00" and booking["note"] == "帶筆電"
    assert booking["createdBy"] == world.aliceActor.userId
    assert booking["resources"] == [{"id": world.room1, "name": "A 會議室", "kind": "room"}]
    assert booking["participants"] == [
      {"employeeId": world.alice, "name": "alice", "role": "organizer"},
      {"employeeId": world.bob, "name": "bob", "role": "attendee"},
    ]
    assert service.getBooking(conn, booking["id"]) == booking


def testAdjacentBookingsDoNotConflict(world):
  with openDb(world.url) as conn:
    service.createBooking(conn, world.aliceActor, inputFor(world))
    service.createBooking(conn, world.bobActor, inputFor(world, startAt=at(11), endAt=at(12)))


def testOverlappingResourceRaisesResourceConflictWithDetails(world):
  with openDb(world.url) as conn:
    first = service.createBooking(conn, world.aliceActor, inputFor(world, title="先建立"))
    error = expectError("RESOURCE_CONFLICT", service.createBooking, conn, world.bobActor, inputFor(world, startAt=at(10, 30), endAt=at(11, 30)))
  assert error.status == 409
  conflict = error.details["conflicts"][0]
  assert conflict == {
    "bookingId": first["id"], "title": "先建立", "startAt": "2026-11-24T10:00:00", "endAt": "2026-11-24T11:00:00",
    "resourceId": world.room1, "resourceName": "A 會議室",
  }


def testDatabaseConstraintIsTheLastLineOfDefense(world, monkeypatch):
  # 模擬並行：先查的時候看不到對方（還沒 commit），寫入時才被資料庫的排除限制擋下
  with openDb(world.url) as conn:
    first = service.createBooking(conn, world.aliceActor, inputFor(world, title="先建立"))
    realFind = service.findResourceConflicts
    calls = []

    def blindFirstCall(*args, **kwargs):
      calls.append(1)
      return [] if len(calls) == 1 else realFind(*args, **kwargs)

    monkeypatch.setattr(service, "findResourceConflicts", blindFirstCall)
    error = expectError("RESOURCE_CONFLICT", service.createBooking, conn, world.bobActor, inputFor(world, title="後到"))
    assert error.details["conflicts"][0]["bookingId"] == first["id"]
    # savepoint 已回復：後到的那筆沒留下任何東西，連線還能用
    assert [item["title"] for item in service.listBookings(conn, at(0), at(23))] == ["先建立"]


def testBookingMayCrossMidnight(world):
  with openDb(world.url) as conn:
    booking = service.createBooking(conn, world.aliceActor, inputFor(world, startAt=at(22), endAt=at(6, day=25)))
    found = service.listBookings(conn, at(0, day=25), at(23, day=25))
    assert [item["id"] for item in found] == [booking["id"]]
    expectError("RESOURCE_CONFLICT", service.createBooking, conn, world.bobActor, inputFor(world, startAt=at(5, day=25), endAt=at(7, day=25)))


def testParticipantOverlapWarnsUnlessAcknowledged(world):
  with openDb(world.url) as conn:
    first = service.createBooking(conn, world.aliceActor, inputFor(world, participantEmployeeIds=[world.bob]))
    second = inputFor(world, resourceIds=[world.room2], startAt=at(10, 30), endAt=at(11, 30), participantEmployeeIds=[world.bob])
    error = expectError("PARTICIPANT_CONFLICT", service.createBooking, conn, world.hrActor, second)
    assert error.status == 409
    conflict = error.details["conflicts"][0]
    assert (conflict["employeeId"], conflict["name"], conflict["bookingId"], conflict["title"]) == (world.bob, "bob", first["id"], "週會")
    assert conflict["reason"] and conflict["startAt"] == "2026-11-24T10:00:00"
    second.acknowledgeWarnings = True
    assert service.createBooking(conn, world.hrActor, second)["status"] == "confirmed"


def testRegisteredUnavailabilityProviderProducesWarning(world):
  def onLeave(conn, employeeIds, startAt, endAt):
    return [{"employeeId": employeeId, "reason": "請假", "startAt": startAt, "endAt": endAt} for employeeId in employeeIds if employeeId == world.bob]

  registerUnavailabilityProvider("leave", onLeave)
  with openDb(world.url) as conn:
    error = expectError("PARTICIPANT_CONFLICT", service.createBooking, conn, world.aliceActor, inputFor(world, participantEmployeeIds=[world.bob]))
    assert [(item["employeeId"], item["reason"], item["name"]) for item in error.details["conflicts"]] == [(world.bob, "請假", "bob")]


def testResourceConflictWinsOverParticipantWarning(world):
  with openDb(world.url) as conn:
    service.createBooking(conn, world.aliceActor, inputFor(world, participantEmployeeIds=[world.bob]))
    expectError("RESOURCE_CONFLICT", service.createBooking, conn, world.hrActor, inputFor(world, participantEmployeeIds=[world.bob]))


def testUpdateExcludesBookingItself(world):
  with openDb(world.url) as conn:
    mine = service.createBooking(conn, world.aliceActor, inputFor(world))
    other = service.createBooking(conn, world.bobActor, inputFor(world, startAt=at(12), endAt=at(13)))
    assert service.updateBooking(conn, world.aliceActor, mine["id"], {"note": "改備註"})["note"] == "改備註"
    assert service.updateBooking(conn, world.aliceActor, mine["id"], {"endAt": at(11, 30)})["endAt"] == "2026-11-24T11:30:00"
    expectError("RESOURCE_CONFLICT", service.updateBooking, conn, world.bobActor, other["id"], {"startAt": at(11), "endAt": at(12, 30)})
    assert service.updateBooking(conn, world.bobActor, other["id"], {"startAt": at(11, 30), "endAt": at(12, 30)})["startAt"] == "2026-11-24T11:30:00"


def testEditingNoteDoesNotRewarnAcknowledgedOverlap(world):
  with openDb(world.url) as conn:
    service.createBooking(conn, world.aliceActor, inputFor(world, participantEmployeeIds=[world.bob]))
    second = service.createBooking(
      conn, world.hrActor, inputFor(world, resourceIds=[world.room2], participantEmployeeIds=[world.bob], acknowledgeWarnings=True)
    )
    assert service.updateBooking(conn, world.hrActor, second["id"], {"note": "只改備註"})["note"] == "只改備註"
    expectError("PARTICIPANT_CONFLICT", service.updateBooking, conn, world.hrActor, second["id"], {"startAt": at(10, 15), "endAt": at(11, 15)})


def testDroppingBusyResourceWhileMovingTimeSucceeds(world):
  with openDb(world.url) as conn:
    service.createBooking(conn, world.bobActor, inputFor(world, resourceIds=[world.room2], startAt=at(14), endAt=at(15)))
    mine = service.createBooking(conn, world.aliceActor, inputFor(world, resourceIds=[world.room1, world.room2]))
    moved = service.updateBooking(conn, world.aliceActor, mine["id"], {"startAt": at(14), "endAt": at(15), "resourceIds": [world.room1]})
    assert [item["id"] for item in moved["resources"]] == [world.room1]


def testUpdateReplacesResourcesAndParticipants(world):
  with openDb(world.url) as conn:
    booking = service.createBooking(conn, world.aliceActor, inputFor(world, participantEmployeeIds=[world.bob]))
    updated = service.updateBooking(
      conn, world.aliceActor, booking["id"], {"resourceIds": [world.room2], "participantEmployeeIds": [world.carol]}
    )
    assert [item["id"] for item in updated["resources"]] == [world.room2]
    assert [(item["employeeId"], item["role"]) for item in updated["participants"]] == [(world.alice, "organizer"), (world.carol, "attendee")]
    moved = service.updateBooking(conn, world.aliceActor, booking["id"], {"organizerEmployeeId": world.bob})
    assert [(item["employeeId"], item["role"]) for item in moved["participants"]] == [(world.bob, "organizer"), (world.alice, "attendee"), (world.carol, "attendee")]


def testCancelFreesResource(world):
  with openDb(world.url) as conn:
    booking = service.createBooking(conn, world.aliceActor, inputFor(world))
    assert service.cancelBooking(conn, world.aliceActor, booking["id"])["status"] == "cancelled"
    assert service.createBooking(conn, world.bobActor, inputFor(world))["status"] == "confirmed"


def testCancelTwiceRaisesAlreadyCancelled(world):
  with openDb(world.url) as conn:
    booking = service.createBooking(conn, world.aliceActor, inputFor(world))
    service.cancelBooking(conn, world.aliceActor, booking["id"])
    error = expectError("ALREADY_CANCELLED", service.cancelBooking, conn, world.aliceActor, booking["id"])
    assert error.status == 409


def testUpdateCancelledRaises(world):
  with openDb(world.url) as conn:
    booking = service.createBooking(conn, world.aliceActor, inputFor(world))
    service.cancelBooking(conn, world.aliceActor, booking["id"])
    error = expectError("BOOKING_CANCELLED", service.updateBooking, conn, world.aliceActor, booking["id"], {"note": "x"})
    assert error.status == 409


def testOnlyCreatorOrWriteAnyMayModify(world):
  with openDb(world.url) as conn:
    booking = service.createBooking(conn, world.aliceActor, inputFor(world))
    error = expectError("FORBIDDEN", service.updateBooking, conn, world.bobActor, booking["id"], {"note": "偷改"})
    assert error.status == 403
    expectError("FORBIDDEN", service.cancelBooking, conn, world.bobActor, booking["id"])
    assert service.updateBooking(conn, world.hrActor, booking["id"], {"note": "人資改"})["note"] == "人資改"
    assert service.cancelBooking(conn, world.adminActor, booking["id"])["status"] == "cancelled"


def testMissingBookingIsNotFound(world):
  with openDb(world.url) as conn:
    expectError("NOT_FOUND", service.getBooking, conn, 9999)
    expectError("NOT_FOUND", service.updateBooking, conn, world.aliceActor, 9999, {"note": "x"})
    expectError("NOT_FOUND", service.cancelBooking, conn, world.aliceActor, 9999)


def testDuplicateResourceAndParticipantIdsAreDeduplicated(world):
  with openDb(world.url) as conn:
    booking = service.createBooking(
      conn, world.aliceActor, inputFor(world, resourceIds=[world.room1, world.room1], participantEmployeeIds=[world.alice, world.bob, world.bob])
    )
  assert len(booking["resources"]) == 1
  assert [(item["employeeId"], item["role"]) for item in booking["participants"]] == [(world.alice, "organizer"), (world.bob, "attendee")]


def testInactiveResourceOrEmployeeIsRejected(world):
  with openDb(world.url) as conn:
    conn.execute("UPDATE resources SET is_active = false WHERE id = %s", (world.room2,))
    conn.execute("UPDATE employees SET is_active = false WHERE id = %s", (world.carol,))
    expectError("INACTIVE_REFERENCE", service.createBooking, conn, world.aliceActor, inputFor(world, resourceIds=[world.room2]))
    error = expectError("INACTIVE_REFERENCE", service.createBooking, conn, world.aliceActor, inputFor(world, participantEmployeeIds=[world.carol]))
    assert error.status == 422
    expectError("VALIDATION", service.createBooking, conn, world.aliceActor, inputFor(world, resourceIds=[9999]))
    expectError("VALIDATION", service.createBooking, conn, world.aliceActor, inputFor(world, participantEmployeeIds=[9999]))


def testExistingBookingStaysEditableAfterResourceIsDeactivated(world):
  with openDb(world.url) as conn:
    booking = service.createBooking(conn, world.aliceActor, inputFor(world))
    conn.execute("UPDATE resources SET is_active = false WHERE id = %s", (world.room1,))
    assert service.updateBooking(conn, world.aliceActor, booking["id"], {"note": "仍可改"})["note"] == "仍可改"


def testAccountWithoutEmployeeNeedsOrganizer(world):
  with openDb(world.url) as conn:
    error = expectError("ORGANIZER_REQUIRED", service.createBooking, conn, world.adminActor, inputFor(world))
    assert error.status == 422
    booking = service.createBooking(conn, world.adminActor, inputFor(world, organizerEmployeeId=world.alice))
  assert booking["createdBy"] == world.adminActor.userId
  assert booking["participants"] == [{"employeeId": world.alice, "name": "alice", "role": "organizer"}]


def testBookingWithoutResourcesIsAllowed(world):
  with openDb(world.url) as conn:
    booking = service.createBooking(conn, world.aliceActor, inputFor(world, resourceIds=[], participantEmployeeIds=[world.bob]))
  assert booking["resources"] == []


def testInvalidTimesTitleAndFieldsAreValidationErrors(world):
  with openDb(world.url) as conn:
    expectError("VALIDATION", service.createBooking, conn, world.aliceActor, inputFor(world, startAt=at(11), endAt=at(11)))
    expectError("VALIDATION", service.createBooking, conn, world.aliceActor, inputFor(world, startAt=at(12), endAt=at(11)))
    expectError("VALIDATION", service.createBooking, conn, world.aliceActor, inputFor(world, title="   "))
    booking = service.createBooking(conn, world.aliceActor, inputFor(world))
    expectError("VALIDATION", service.updateBooking, conn, world.aliceActor, booking["id"], {"createdBy": 1})
    expectError("VALIDATION", service.updateBooking, conn, world.aliceActor, booking["id"], {"endAt": at(9)})


def testAuditRowsForCreateUpdateCancel(world):
  with openDb(world.url) as conn:
    booking = service.createBooking(conn, world.aliceActor, inputFor(world))
    service.updateBooking(conn, world.aliceActor, booking["id"], {"title": "改標題"})
    service.cancelBooking(conn, world.aliceActor, booking["id"])
    rows = [row for row in listAudit(conn, module="booking") if row["entity"] == "booking"]
  assert [row["action"] for row in reversed(rows)] == ["createBooking", "updateBooking", "cancelBooking"]
  created, updated, cancelled = reversed(rows)
  assert created["before"] is None and created["after"]["title"] == "週會"
  assert (updated["before"]["title"], updated["after"]["title"]) == ("週會", "改標題")
  assert cancelled["after"]["status"] == "cancelled" and cancelled["userId"] == world.aliceActor.userId


def testResourceCreateUpdateListAndAudit(world):
  with openDb(world.url) as conn:
    resource = service.createResource(conn, world.adminActor, {"name": "投影機", "kind": "equipment", "features": ["hdmi"], "note": "三樓"})
    assert resource["features"] == ["hdmi"] and resource["isActive"] is True and resource["capacity"] is None
    expectError("DUPLICATE", service.createResource, conn, world.adminActor, {"name": "投影機", "kind": "equipment"})
    expectError("VALIDATION", service.createResource, conn, world.adminActor, {"name": " ", "kind": "room"})
    expectError("VALIDATION", service.createResource, conn, world.adminActor, {"name": "X", "kind": "person"})
    updated = service.updateResource(conn, world.adminActor, resource["id"], {"isActive": False, "location": "四樓"})
    assert (updated["isActive"], updated["location"]) == (False, "四樓")
    assert resource["id"] not in [item["id"] for item in service.listResources(conn)]
    assert resource["id"] in [item["id"] for item in service.listResources(conn, includeInactive=True)]
    expectError("NOT_FOUND", service.updateResource, conn, world.adminActor, 9999, {"name": "x"})
    actions = [row["action"] for row in listAudit(conn, module="booking") if row["entity"] == "resource"]
  assert "createResource" in actions and "updateResource" in actions


def testListBookingsFiltersByResourceAndEmployeeAndHidesCancelled(world):
  with openDb(world.url) as conn:
    inRoom1 = service.createBooking(conn, world.aliceActor, inputFor(world))
    inRoom2 = service.createBooking(conn, world.bobActor, inputFor(world, resourceIds=[world.room2], startAt=at(12), endAt=at(13)))
    cancelled = service.createBooking(conn, world.bobActor, inputFor(world, resourceIds=[world.room2], startAt=at(14), endAt=at(15)))
    service.cancelBooking(conn, world.bobActor, cancelled["id"])
    start, end = at(0), at(23)
    assert [item["id"] for item in service.listBookings(conn, start, end)] == [inRoom1["id"], inRoom2["id"]]
    assert [item["id"] for item in service.listBookings(conn, start, end, resourceId=world.room2)] == [inRoom2["id"]]
    assert [item["id"] for item in service.listBookings(conn, start, end, employeeId=world.alice)] == [inRoom1["id"]]
    assert len(service.listBookings(conn, start, end, includeCancelled=True)) == 3
    # 範圍邊界：剛好在 11:00 結束的預約，不算在 11:00 之後的範圍裡
    assert service.listBookings(conn, at(11), at(12)) == []


def testSummaryUsesNowForTodayNextAndCurrent(world):
  with openDb(world.url) as conn:
    past = service.createBooking(conn, world.aliceActor, inputFor(world, resourceIds=[], startAt=at(9), endAt=at(10)))
    current = service.createBooking(conn, world.aliceActor, inputFor(world, startAt=at(10), endAt=at(11)))
    following = service.createBooking(conn, world.aliceActor, inputFor(world, startAt=at(14), endAt=at(15)))
    tomorrow = service.createBooking(conn, world.aliceActor, inputFor(world, startAt=at(9, day=25), endAt=at(10, day=25)))
    cancelled = service.createBooking(conn, world.aliceActor, inputFor(world, startAt=at(12), endAt=at(13)))
    service.cancelBooking(conn, world.aliceActor, cancelled["id"])
    inactive = service.createResource(conn, world.adminActor, {"name": "停用的", "kind": "room"})
    service.updateResource(conn, world.adminActor, inactive["id"], {"isActive": False})
    summary = service.getSummary(conn, at(10, 30))
  assert [item["id"] for item in summary["todayBookings"]] == [past["id"], current["id"], following["id"]]
  assert summary["nextBooking"]["id"] == following["id"]
  assert summary["resourceCount"] == 2 and summary["bookingCount"] == 3
  status = {item["resourceId"]: item for item in summary["resourceStatus"]}
  assert status[world.room1]["currentBooking"]["id"] == current["id"] and status[world.room2]["currentBooking"] is None
  assert set(status[world.room1]) == {"resourceId", "name", "kind", "currentBooking"}
  assert tomorrow["id"] not in [item["id"] for item in summary["todayBookings"]]
