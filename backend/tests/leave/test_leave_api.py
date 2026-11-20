from types import SimpleNamespace

import pytest


def errorOf(response):
  return response.json()["error"]


@pytest.fixture
def world(client, newClient, loginAs):
  w = SimpleNamespace()
  w.admin = newClient()
  loginAs("admin", "admin@example.com", client=w.admin)
  w.bossClient = newClient()
  w.boss = loginAs("manager", "boss@example.com", employee=True, client=w.bossClient)
  w.aliceClient = client
  w.alice = loginAs("employee", "alice@example.com", employee=True)
  w.bobClient = newClient()
  w.bob = loginAs("employee", "bob@example.com", employee=True, client=w.bobClient)
  w.hrClient = newClient()
  w.hr = loginAs("hr", "hr@example.com", employee=True, client=w.hrClient)
  response = w.admin.patch(f"/api/org/employees/{w.alice['employeeId']}", json={"managerId": w.boss["employeeId"]})
  assert response.status_code == 200, response.text
  w.types = {item["code"]: item["id"] for item in w.aliceClient.get("/api/leave/types").json()}
  return w


def body(w, code="personal", startAt="2026-11-24T09:00", endAt="2026-11-24T18:00", **extra):
  return {"leaveTypeId": w.types[code], "startAt": startAt, "endAt": endAt, **extra}


def testModulesListIncludesLeave(world):
  modules = {item["name"]: item["permissions"] for item in world.aliceClient.get("/api/modules").json()}
  assert modules["leave"] == ["leave.request"]
  modules = {item["name"]: item["permissions"] for item in world.hrClient.get("/api/modules").json()}
  assert modules["leave"] == ["leave.request", "leave.manage"]


def testSubmitApproveFlowUpdatesBalance(world):
  quote = world.aliceClient.post("/api/leave/requests/quote", json=body(world, "annual"))
  assert quote.status_code == 200 and quote.json() == {"hours": 8, "remainingAfter": 48, "conflicts": []}
  created = world.aliceClient.post("/api/leave/requests", json=body(world, "annual", reason="看醫生"))
  assert created.status_code == 201, created.text
  requestId = created.json()["id"]
  toApprove = world.bossClient.get("/api/leave/requests", params={"scope": "toApprove"}).json()
  assert [item["id"] for item in toApprove] == [requestId]
  approved = world.bossClient.post(f"/api/leave/requests/{requestId}/approve", json={"note": "OK"})
  assert approved.status_code == 200 and approved.json()["status"] == "approved"
  balances = world.aliceClient.get("/api/leave/balances", params={"on": "2026-11-21"}).json()
  annual = next(item for item in balances if item["quotaKind"] == "seniority")
  assert annual["approvedHours"] == 8 and annual["remainingHours"] == 48


def testErrorStatusesAndCodes(world):
  response = world.aliceClient.post("/api/leave/requests", json=body(world, startAt="2026-11-28T09:00", endAt="2026-11-28T18:00"))
  assert response.status_code == 422 and errorOf(response)["code"] == "LEAVE_NO_WORKING_HOURS"
  response = world.aliceClient.post("/api/leave/requests", json=body(world, startAt="2026-11-24T09:00+08:00"))
  assert response.status_code == 422 and errorOf(response)["code"] == "VALIDATION"
  world.aliceClient.post("/api/leave/requests", json=body(world))
  response = world.aliceClient.post("/api/leave/requests", json=body(world, "sick"))
  assert response.status_code == 409 and errorOf(response)["code"] == "LEAVE_OVERLAP"
  response = world.admin.post("/api/leave/requests", json=body(world))
  assert response.status_code == 422 and errorOf(response)["code"] == "NO_EMPLOYEE"


def testPermissions(world):
  created = world.aliceClient.post("/api/leave/requests", json=body(world)).json()
  assert world.bobClient.post(f"/api/leave/requests/{created['id']}/approve", json={}).status_code == 403
  assert world.bobClient.get(f"/api/leave/requests/{created['id']}").status_code == 403
  assert world.bobClient.get("/api/leave/balances", params={"employeeId": world.alice["employeeId"]}).status_code == 403
  assert world.bossClient.get("/api/leave/balances", params={"employeeId": world.alice["employeeId"]}).status_code == 200
  assert world.bossClient.get("/api/leave/requests", params={"scope": "all"}).status_code == 403
  assert world.aliceClient.get("/api/leave/types", params={"includeInactive": "true"}).status_code == 403
  assert world.aliceClient.post("/api/leave/types", json={"code": "x", "name": "某假", "paidRatio": 1, "quotaKind": "none"}).status_code == 403
  assert world.aliceClient.get("/api/leave/unused", params={"periodEndFrom": "2026-01-01", "periodEndTo": "2026-12-31"}).status_code == 403
  assert world.hrClient.post(f"/api/leave/requests/{created['id']}/approve", json={}).status_code == 200


def testRejectWithdrawCancelEndpoints(world):
  first = world.aliceClient.post("/api/leave/requests", json=body(world)).json()
  response = world.bossClient.post(f"/api/leave/requests/{first['id']}/reject", json={})
  assert response.status_code == 422
  assert world.bossClient.post(f"/api/leave/requests/{first['id']}/reject", json={"note": "不行"}).json()["status"] == "rejected"
  second = world.aliceClient.post("/api/leave/requests", json=body(world)).json()
  assert world.aliceClient.post(f"/api/leave/requests/{second['id']}/withdraw").json()["status"] == "withdrawn"
  third = world.aliceClient.post("/api/leave/requests", json=body(world, startAt="2030-01-07T09:00", endAt="2030-01-07T18:00")).json()
  world.bossClient.post(f"/api/leave/requests/{third['id']}/approve", json={})
  response = world.aliceClient.post(f"/api/leave/requests/{third['id']}/cancel")
  assert response.status_code == 200 and response.json()["status"] == "cancelled"


def testLeaveTypesAdjustmentsAndUnusedForHr(world):
  created = world.hrClient.post("/api/leave/types", json={"code": "family", "name": "家庭照顧假", "paidRatio": 0, "quotaKind": "yearly_cap", "annualCapHours": 56})
  assert created.status_code == 201, created.text
  updated = world.hrClient.patch(f"/api/leave/types/{created.json()['id']}", json={"isActive": False})
  assert updated.json()["isActive"] is False
  response = world.hrClient.patch(f"/api/leave/types/{created.json()['id']}", json={"quotaKind": "none"})
  assert response.status_code == 422 and errorOf(response)["details"] == {"field": "quotaKind"}
  adjustment = world.hrClient.post("/api/leave/adjustments", json={
    "employeeId": world.alice["employeeId"], "leaveTypeId": world.types["personal"], "periodStart": "2026-01-01", "hours": 8, "reason": "補給",
  })
  assert adjustment.status_code == 201, adjustment.text
  assert len(world.hrClient.get("/api/leave/adjustments", params={"employeeId": world.alice["employeeId"]}).json()) == 1
  unused = world.hrClient.get("/api/leave/unused", params={"periodEndFrom": "2025-12-01", "periodEndTo": "2025-12-31"})
  assert unused.status_code == 200 and len(unused.json()) == 4


def testCalendarEndpointHidesType(world):
  world.aliceClient.post("/api/leave/requests", json=body(world))
  params = {"from": "2026-11-24T00:00", "to": "2026-11-25T00:00"}
  assert world.bobClient.get("/api/leave/calendar", params=params).json()[0]["leaveTypeName"] is None
  assert world.bossClient.get("/api/leave/calendar", params=params).json()[0]["leaveTypeName"] == "事假"


def testBookingWarnsAboutParticipantOnLeave(world):
  # createApp 會呼叫 leave/router.py 的 onAppCreated 登記不可用提供者
  world.aliceClient.post("/api/leave/requests", json=body(world))
  room = world.admin.post("/api/booking/resources", json={"name": "A 會議室", "kind": "room"}).json()["id"]
  response = world.bossClient.post("/api/booking/bookings", json={
    "title": "週會", "category": "會議", "startAt": "2026-11-24T10:00", "endAt": "2026-11-24T11:00",
    "resourceIds": [room], "participantEmployeeIds": [world.alice["employeeId"]],
  })
  assert response.status_code == 409 and errorOf(response)["code"] == "PARTICIPANT_CONFLICT"
  assert errorOf(response)["details"]["conflicts"][0]["reason"] == "請假（待核准）"


def testMeetingConflictEndpoint(world):
  room = world.admin.post("/api/booking/resources", json={"name": "A 會議室", "kind": "room"}).json()["id"]
  world.bossClient.post("/api/booking/bookings", json={
    "title": "週會", "category": "會議", "startAt": "2026-11-24T10:00", "endAt": "2026-11-24T11:00",
    "resourceIds": [room], "participantEmployeeIds": [world.alice["employeeId"]],
  })
  response = world.aliceClient.post("/api/leave/requests", json=body(world))
  assert response.status_code == 409 and errorOf(response)["code"] == "MEETING_CONFLICT"
  assert world.aliceClient.post("/api/leave/requests", json=body(world, acknowledgeWarnings=True)).status_code == 201
