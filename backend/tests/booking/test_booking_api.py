from types import SimpleNamespace

import pytest


def errorOf(response):
  return response.json()["error"]


@pytest.fixture
def world(client, newClient, loginAs):
  w = SimpleNamespace()
  w.admin = newClient()
  loginAs("admin", "admin@example.com", client=w.admin)
  w.room1 = w.admin.post("/api/booking/resources", json={"name": "A 會議室", "kind": "room"}).json()["id"]
  w.room2 = w.admin.post("/api/booking/resources", json={"name": "B 會議室", "kind": "room"}).json()["id"]
  w.aliceClient = client
  w.alice = loginAs("employee", "alice@example.com", employee=True)
  w.bobClient = newClient()
  w.bob = loginAs("employee", "bob@example.com", employee=True, client=w.bobClient)
  w.hrClient = newClient()
  w.hr = loginAs("hr", "hr@example.com", employee=True, client=w.hrClient)
  return w


def bodyFor(w, **overrides):
  body = {
    "title": "週會", "category": "會議", "startAt": "2026-11-24T10:00", "endAt": "2026-11-24T11:00",
    "resourceIds": [w.room1], "participantEmployeeIds": [],
  }
  body.update(overrides)
  return body


def testCreateBookingReturns201WithResourcesAndParticipants(world):
  response = world.aliceClient.post("/api/booking/bookings", json=bodyFor(world, participantEmployeeIds=[world.bob["employeeId"]], note="帶筆電"))
  assert response.status_code == 201, response.text
  booking = response.json()
  assert booking["status"] == "confirmed" and booking["startAt"] == "2026-11-24T10:00:00" and booking["note"] == "帶筆電"
  assert booking["resources"] == [{"id": world.room1, "name": "A 會議室", "kind": "room"}]
  assert [(item["employeeId"], item["role"]) for item in booking["participants"]] == [
    (world.alice["employeeId"], "organizer"), (world.bob["employeeId"], "attendee"),
  ]
  assert booking["createdBy"] == world.alice["userId"]


def testResourceConflictIs409WithDetails(world):
  world.aliceClient.post("/api/booking/bookings", json=bodyFor(world, title="先建立"))
  response = world.bobClient.post("/api/booking/bookings", json=bodyFor(world, startAt="2026-11-24T10:30", endAt="2026-11-24T11:30"))
  assert response.status_code == 409
  assert errorOf(response)["code"] == "RESOURCE_CONFLICT"
  assert errorOf(response)["details"]["conflicts"][0]["title"] == "先建立"
  assert errorOf(response)["details"]["conflicts"][0]["resourceName"] == "A 會議室"


def testParticipantConflictThenAcknowledgeRetry(world):
  bobId = world.bob["employeeId"]
  world.aliceClient.post("/api/booking/bookings", json=bodyFor(world, participantEmployeeIds=[bobId]))
  second = bodyFor(world, resourceIds=[world.room2], startAt="2026-11-24T10:30", endAt="2026-11-24T11:30", participantEmployeeIds=[bobId])
  first = world.hrClient.post("/api/booking/bookings", json=second)
  assert first.status_code == 409 and errorOf(first)["code"] == "PARTICIPANT_CONFLICT"
  assert errorOf(first)["details"]["conflicts"][0]["employeeId"] == bobId
  retry = world.hrClient.post("/api/booking/bookings", json={**second, "acknowledgeWarnings": True})
  assert retry.status_code == 201


def testCrossMidnightBookingAccepted(world):
  response = world.aliceClient.post("/api/booking/bookings", json=bodyFor(world, startAt="2026-11-24T22:00", endAt="2026-11-25T06:00"))
  assert response.status_code == 201
  found = world.aliceClient.get("/api/booking/bookings", params={"from": "2026-11-25T00:00", "to": "2026-11-25T23:59"}).json()
  assert [item["id"] for item in found] == [response.json()["id"]]


@pytest.mark.parametrize("text", ["2026-11-24T10:00+08:00", "2026-11-24T10:00Z", "2026/11/24 10:00"])
def testTimeWithTimezoneOrBadFormatIs422(world, text):
  response = world.aliceClient.post("/api/booking/bookings", json=bodyFor(world, startAt=text))
  assert response.status_code == 422 and errorOf(response)["code"] == "VALIDATION"


def testEndBeforeStartIs422(world):
  response = world.aliceClient.post("/api/booking/bookings", json=bodyFor(world, startAt="2026-11-24T11:00", endAt="2026-11-24T10:00"))
  assert response.status_code == 422 and errorOf(response)["code"] == "VALIDATION"


def testInvalidBodyIs422(world):
  body = bodyFor(world)
  del body["title"]
  response = world.aliceClient.post("/api/booking/bookings", json=body)
  assert response.status_code == 422 and errorOf(response)["code"] == "VALIDATION"


def testNonCreatorPatchIs403AndHrPatchIs200(world):
  bookingId = world.aliceClient.post("/api/booking/bookings", json=bodyFor(world)).json()["id"]
  denied = world.bobClient.patch(f"/api/booking/bookings/{bookingId}", json={"note": "偷改"})
  assert denied.status_code == 403 and errorOf(denied)["code"] == "FORBIDDEN"
  assert world.bobClient.post(f"/api/booking/bookings/{bookingId}/cancel").status_code == 403
  allowed = world.hrClient.patch(f"/api/booking/bookings/{bookingId}", json={"note": "人資改", "endAt": "2026-11-24T11:30"})
  assert allowed.status_code == 200 and allowed.json()["note"] == "人資改" and allowed.json()["endAt"] == "2026-11-24T11:30:00"
  own = world.aliceClient.patch(f"/api/booking/bookings/{bookingId}", json={"resourceIds": [world.room2]})
  assert own.status_code == 200 and [item["id"] for item in own.json()["resources"]] == [world.room2]


def testCancelThenRebookSameSlot(world):
  bookingId = world.aliceClient.post("/api/booking/bookings", json=bodyFor(world)).json()["id"]
  cancelled = world.aliceClient.post(f"/api/booking/bookings/{bookingId}/cancel")
  assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
  assert world.bobClient.post("/api/booking/bookings", json=bodyFor(world)).status_code == 201
  again = world.aliceClient.post(f"/api/booking/bookings/{bookingId}/cancel")
  assert again.status_code == 409 and errorOf(again)["code"] == "ALREADY_CANCELLED"
  edit = world.aliceClient.patch(f"/api/booking/bookings/{bookingId}", json={"note": "x"})
  assert edit.status_code == 409 and errorOf(edit)["code"] == "BOOKING_CANCELLED"


def testMissingBookingIs404(world):
  assert world.aliceClient.patch("/api/booking/bookings/9999", json={"note": "x"}).status_code == 404
  assert world.aliceClient.post("/api/booking/bookings/9999/cancel").status_code == 404


def testEmployeeCannotCreateResourceButAdminCan(world):
  denied = world.aliceClient.post("/api/booking/resources", json={"name": "投影機", "kind": "equipment"})
  assert denied.status_code == 403 and errorOf(denied)["code"] == "FORBIDDEN"
  assert world.hrClient.post("/api/booking/resources", json={"name": "投影機", "kind": "equipment"}).status_code == 403
  created = world.admin.post("/api/booking/resources", json={"name": "投影機", "kind": "equipment", "features": ["hdmi"], "capacity": None})
  assert created.status_code == 201 and created.json()["features"] == ["hdmi"] and created.json()["isActive"] is True
  resourceId = created.json()["id"]
  assert world.aliceClient.patch(f"/api/booking/resources/{resourceId}", json={"isActive": False}).status_code == 403
  disabled = world.admin.patch(f"/api/booking/resources/{resourceId}", json={"isActive": False, "location": "三樓"})
  assert disabled.status_code == 200 and disabled.json()["isActive"] is False
  assert resourceId not in [item["id"] for item in world.aliceClient.get("/api/booking/resources").json()]
  listed = world.aliceClient.get("/api/booking/resources", params={"includeInactive": "true"}).json()
  assert resourceId in [item["id"] for item in listed]
  assert world.admin.post("/api/booking/resources", json={"name": "投影機", "kind": "equipment"}).status_code == 409
  assert world.admin.post("/api/booking/resources", json={"name": "X", "kind": "person"}).status_code == 422


def testListFiltersAndRequiresRange(world):
  mine = world.aliceClient.post("/api/booking/bookings", json=bodyFor(world)).json()["id"]
  other = world.bobClient.post("/api/booking/bookings", json=bodyFor(world, resourceIds=[world.room2], startAt="2026-11-24T12:00", endAt="2026-11-24T13:00")).json()["id"]
  gone = world.bobClient.post("/api/booking/bookings", json=bodyFor(world, resourceIds=[world.room2], startAt="2026-11-24T14:00", endAt="2026-11-24T15:00")).json()["id"]
  world.bobClient.post(f"/api/booking/bookings/{gone}/cancel")
  rangeParams = {"from": "2026-11-24T00:00", "to": "2026-11-24T23:59"}
  assert [item["id"] for item in world.aliceClient.get("/api/booking/bookings", params=rangeParams).json()] == [mine, other]
  assert [item["id"] for item in world.aliceClient.get("/api/booking/bookings", params={**rangeParams, "resourceId": world.room2}).json()] == [other]
  assert [item["id"] for item in world.aliceClient.get("/api/booking/bookings", params={**rangeParams, "employeeId": world.alice["employeeId"]}).json()] == [mine]
  assert len(world.aliceClient.get("/api/booking/bookings", params={**rangeParams, "includeCancelled": "true"}).json()) == 3
  missing = world.aliceClient.get("/api/booking/bookings", params={"to": "2026-11-24T23:59"})
  assert missing.status_code == 422 and errorOf(missing)["code"] == "VALIDATION"
  assert world.aliceClient.get("/api/booking/bookings", params={"from": "2026-11-24T00:00+08:00", "to": "2026-11-24T23:59"}).status_code == 422


def testSummaryEndpointShape(world):
  response = world.aliceClient.get("/api/booking/summary")
  assert response.status_code == 200
  summary = response.json()
  assert set(summary) == {"todayBookings", "nextBooking", "resourceStatus", "bookingCount", "resourceCount"}
  assert summary["resourceCount"] == 2 and len(summary["resourceStatus"]) == 2
  assert set(summary["resourceStatus"][0]) == {"resourceId", "name", "kind", "currentBooking"}


def testAdminWithoutEmployeeMustPassOrganizer(world):
  response = world.admin.post("/api/booking/bookings", json=bodyFor(world))
  assert response.status_code == 422 and errorOf(response)["code"] == "ORGANIZER_REQUIRED"
  created = world.admin.post("/api/booking/bookings", json=bodyFor(world, organizerEmployeeId=world.alice["employeeId"]))
  assert created.status_code == 201
  assert created.json()["participants"][0]["employeeId"] == world.alice["employeeId"]


def testUnauthenticatedIs401(client):
  assert client.get("/api/booking/summary").status_code == 401
  assert client.get("/api/booking/resources").status_code == 401
  assert client.get("/api/booking/bookings", params={"from": "2026-11-24T00:00", "to": "2026-11-24T23:59"}).status_code == 401
  assert client.post("/api/booking/bookings", json={}).status_code == 401


def testNullListFieldsInPatchAreValidationErrors(world):
  bookingId = world.aliceClient.post("/api/booking/bookings", json=bodyFor(world)).json()["id"]
  for field in ("resourceIds", "participantEmployeeIds"):
    response = world.aliceClient.patch(f"/api/booking/bookings/{bookingId}", json={field: None})
    assert response.status_code == 422 and errorOf(response)["code"] == "VALIDATION", field
  response = world.aliceClient.patch(f"/api/booking/bookings/{bookingId}", json={"startAt": None})
  assert response.status_code == 422 and errorOf(response)["code"] == "VALIDATION"
