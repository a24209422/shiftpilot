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
  # 主管只能排今天以後的班；用很遠的星期一，測試哪天跑都一樣
  body = {"employeeId": alice, "effectiveFrom": "2030-01-07", "days": [{"weekday": weekday, "shiftTypeId": world.evening} for weekday in range(5)]}
  assert world.bobClient.post("/api/shift/rosters", json=body).status_code == 403
  created = world.bossClient.post("/api/shift/rosters", json=body)
  assert created.status_code == 201, created.text
  rows = world.bobClient.get("/api/shift/schedule", params={"from": "2030-01-07", "to": "2030-01-08", "employeeIds": str(alice)}).json()
  assert [(row["day"], row["source"], row["shiftName"]) for row in rows] == [("2030-01-07", "roster", "晚班"), ("2030-01-08", "roster", "晚班")]
  assert world.bobClient.get("/api/shift/rosters", params={"employeeId": alice}).json()[0]["id"] == created.json()["id"]
  # 只能刪還沒生效的班表；用很遠的日期，測試哪天跑都一樣
  future = world.bossClient.post("/api/shift/rosters", json={**body, "effectiveFrom": "2030-02-04"}).json()
  assert world.bossClient.delete(f"/api/shift/rosters/{future['id']}").status_code == 204
  # 已生效的班表用固定的過去日期，不隨測試執行的日期變動
  # 過去的班只有人資能排；主管刪它時要被「已生效」擋下
  past = world.hrClient.post("/api/shift/rosters", json={**body, "effectiveFrom": "2026-01-05"})
  assert past.status_code == 201, past.text
  response = world.bossClient.delete(f"/api/shift/rosters/{past.json()['id']}")
  assert response.status_code == 409 and errorOf(response)["code"] == "ROSTER_ALREADY_EFFECTIVE"


def testOverrideEndpoints(world):
  alice = world.alice["employeeId"]
  # 主管只能排今天以後的班；用很遠的日期，測試哪天跑都一樣
  body = {"employeeId": alice, "day": "2030-01-08", "shiftTypeId": None, "note": "補休"}
  assert world.bobClient.put("/api/shift/overrides", json=body).status_code == 403
  saved = world.bossClient.put("/api/shift/overrides", json=body)
  assert saved.status_code == 200 and saved.json()["note"] == "補休"
  listed = world.aliceClient.get("/api/shift/overrides", params={"employeeId": alice, "from": "2030-01-07", "to": "2030-01-13"}).json()
  assert [item["day"] for item in listed] == ["2030-01-08"]
  assert world.hrClient.delete(f"/api/shift/overrides/{alice}/2030-01-08").status_code == 204
  assert world.hrClient.delete(f"/api/shift/overrides/{alice}/2030-01-08").status_code == 404


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


def testOwnOffShiftIsNotWarned(world):
  # 2026-11-28 是星期六：送出的人自己休息，不提醒自己
  body = booking(world, "2026-11-28T10:00", "2026-11-28T11:00", world.bob["employeeId"])
  response = world.bossClient.post("/api/booking/bookings", json={**body, "participantEmployeeIds": []})
  assert response.status_code == 201, response.text


def testOrganizerChosenByHrIsStillWarned(world):
  body = booking(world, "2026-11-28T10:00", "2026-11-28T11:00", world.alice["employeeId"])
  response = world.hrClient.post("/api/booking/bookings", json={**body, "organizerEmployeeId": world.bob["employeeId"]})
  assert response.status_code == 409
  reasons = {(item["employeeId"], item["reason"]) for item in errorOf(response)["details"]["conflicts"]}
  assert (world.bob["employeeId"], "休息日") in reasons and (world.alice["employeeId"], "休息日") in reasons
  assert world.hr["employeeId"] not in {employeeId for employeeId, _ in reasons}


def testOwnLeaveIsStillWarned(world):
  types = {item["code"]: item["id"] for item in world.bossClient.get("/api/leave/types").json()}
  leave = world.bossClient.post("/api/leave/requests", json={"leaveTypeId": types["personal"], "startAt": "2026-11-24T09:00", "endAt": "2026-11-24T18:00"})
  assert leave.status_code == 201, leave.text
  body = booking(world, "2026-11-24T10:00", "2026-11-24T11:00", world.bob["employeeId"])
  response = world.bossClient.post("/api/booking/bookings", json={**body, "participantEmployeeIds": []})
  assert response.status_code == 409
  assert [item["reason"] for item in errorOf(response)["details"]["conflicts"]] == ["請假（待核准）"]
