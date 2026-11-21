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
  assert w.admin.patch(f"/api/org/employees/{w.alice['employeeId']}", json={"managerId": w.boss["employeeId"]}).status_code == 200
  created = w.hrClient.post("/api/shift/types", json={"code": "evening", "name": "晚班", "startTime": "14:00", "endTime": "23:00", "breakStart": "18:00", "breakEnd": "19:00"})
  assert created.status_code == 201, created.text
  w.evening = created.json()["id"]
  return w


def booking(w, startAt, endAt, participantId):
  room = w.admin.post("/api/booking/resources", json={"name": f"會議室{startAt}", "kind": "room"}).json()["id"]
  return {"title": "週會", "category": "會議", "startAt": startAt, "endAt": endAt, "resourceIds": [room], "participantEmployeeIds": [participantId]}


def testModulesListIncludesShift(world):
  modules = {item["name"]: item["permissions"] for item in world.aliceClient.get("/api/modules").json()}
  assert modules["shift"] == ["shift.read"]


def testTypeEndpointsAndPermissions(world):
  assert world.aliceClient.post("/api/shift/types", json={"code": "x", "name": "某班", "startTime": "10:00", "endTime": "19:00"}).status_code == 403
  assert world.aliceClient.get("/api/shift/types", params={"includeInactive": "true"}).status_code == 403
  assert [item["code"] for item in world.aliceClient.get("/api/shift/types").json()] == ["standard", "evening"]
  response = world.hrClient.patch(f"/api/shift/types/{world.evening}", json={"startTime": "13:00"})
  assert response.status_code == 422 and errorOf(response)["code"] == "SHIFT_TYPE_IMMUTABLE"
  standard = world.aliceClient.get("/api/shift/types").json()[0]["id"]
  response = world.hrClient.patch(f"/api/shift/types/{standard}", json={"isActive": False})
  assert response.status_code == 409 and errorOf(response)["code"] == "SHIFT_DEFAULT_REQUIRED"


def testManagerSchedulesSubordinateAndScheduleReflectsIt(world):
  alice = world.alice["employeeId"]
  body = {"employeeId": alice, "effectiveFrom": "2026-11-23", "days": [{"weekday": weekday, "shiftTypeId": world.evening} for weekday in range(5)]}
  assert world.bobClient.post("/api/shift/rosters", json=body).status_code == 403
  created = world.bossClient.post("/api/shift/rosters", json=body)
  assert created.status_code == 201, created.text
  rows = world.bobClient.get("/api/shift/schedule", params={"from": "2026-11-23", "to": "2026-11-24", "employeeIds": str(alice)}).json()
  assert [(row["day"], row["source"], row["shiftName"]) for row in rows] == [("2026-11-23", "roster", "晚班"), ("2026-11-24", "roster", "晚班")]
  assert world.bobClient.get("/api/shift/rosters", params={"employeeId": alice}).json()[0]["id"] == created.json()["id"]
  # 只能刪還沒生效的班表；用很遠的日期，測試哪天跑都一樣
  future = world.bossClient.post("/api/shift/rosters", json={**body, "effectiveFrom": "2030-01-07"}).json()
  assert world.bossClient.delete(f"/api/shift/rosters/{future['id']}").status_code == 204
  # 已生效的班表用固定的過去日期，不隨測試執行的日期變動
  past = world.bossClient.post("/api/shift/rosters", json={**body, "effectiveFrom": "2026-01-05"})
  assert past.status_code == 201, past.text
  response = world.bossClient.delete(f"/api/shift/rosters/{past.json()['id']}")
  assert response.status_code == 409 and errorOf(response)["code"] == "ROSTER_ALREADY_EFFECTIVE"


def testOverrideEndpoints(world):
  alice = world.alice["employeeId"]
  body = {"employeeId": alice, "day": "2026-11-24", "shiftTypeId": None, "note": "補休"}
  assert world.bobClient.put("/api/shift/overrides", json=body).status_code == 403
  saved = world.bossClient.put("/api/shift/overrides", json=body)
  assert saved.status_code == 200 and saved.json()["note"] == "補休"
  listed = world.aliceClient.get("/api/shift/overrides", params={"employeeId": alice, "from": "2026-11-23", "to": "2026-11-29"}).json()
  assert [item["day"] for item in listed] == ["2026-11-24"]
  assert world.hrClient.delete(f"/api/shift/overrides/{alice}/2026-11-24").status_code == 204
  assert world.hrClient.delete(f"/api/shift/overrides/{alice}/2026-11-24").status_code == 404


def testScheduleValidation(world):
  response = world.aliceClient.get("/api/shift/schedule", params={"from": "2026-11-01", "to": "2026-12-15"})
  assert response.status_code == 422
  response = world.aliceClient.get("/api/shift/schedule", params={"from": "2026-11-23", "to": "2026-11-23", "employeeIds": "1,x"})
  assert response.status_code == 422


def testBookingWarnsWhenParticipantOffShift(world):
  bob = world.bob["employeeId"]
  # 2026-11-28 是星期六：沒排班的人休息
  response = world.bossClient.post("/api/booking/bookings", json=booking(world, "2026-11-28T10:00", "2026-11-28T11:00", bob))
  assert response.status_code == 409 and errorOf(response)["code"] == "PARTICIPANT_CONFLICT"
  assert "休息日" in [item["reason"] for item in errorOf(response)["details"]["conflicts"]]
  response = world.bossClient.post("/api/booking/bookings", json=booking(world, "2026-11-24T17:00", "2026-11-24T19:00", bob))
  assert response.status_code == 409
  assert "不在班（09:00–18:00）" in [item["reason"] for item in errorOf(response)["details"]["conflicts"]]


def testBookingInsideShiftAndAtLunchHasNoShiftWarning(world):
  bob = world.bob["employeeId"]
  for startAt, endAt in (("2026-11-24T10:00", "2026-11-24T11:00"), ("2026-11-24T12:00", "2026-11-24T13:00")):
    response = world.bossClient.post("/api/booking/bookings", json=booking(world, startAt, endAt, bob))
    assert response.status_code == 201, response.text
