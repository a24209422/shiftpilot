def errorOf(response):
  return response.json()["error"]


def createDepartment(client, name="工程部", **extra):
  response = client.post("/api/org/departments", json={"name": name, **extra})
  assert response.status_code == 201, response.text
  return response.json()


def employeeBody(departmentId, **extra):
  return {"employeeNo": "E001", "name": "王小明", "departmentId": departmentId, "jobTitle": "工程師", "hiredOn": "2025-01-01", **extra}


def createEmployee(client, departmentId, **extra):
  response = client.post("/api/org/employees", json=employeeBody(departmentId, **extra))
  assert response.status_code == 201, response.text
  return response.json()


def testEmployeeCanReadButNotWrite(client, newClient, loginAs):
  hrClient = newClient()
  loginAs("hr", client=hrClient)
  departmentId = createDepartment(hrClient)["id"]
  loginAs("employee")
  assert client.get("/api/org/employees").status_code == 200
  assert client.get("/api/org/departments").status_code == 200
  response = client.post("/api/org/employees", json=employeeBody(departmentId))
  assert response.status_code == 403 and errorOf(response)["code"] == "FORBIDDEN"
  assert client.post("/api/org/departments", json={"name": "x"}).status_code == 403
  assert client.put("/api/org/calendarDays/2026-10-10", json={"kind": "holiday", "name": "國慶日"}).status_code == 403


def testHrCanCreateDepartmentAndEmployee(client, loginAs):
  loginAs("hr")
  department = createDepartment(client)
  assert set(department) == {"id", "name", "parentId"} and department["parentId"] is None
  employee = createEmployee(client, department["id"], email="a@x.com")
  assert employee["employeeNo"] == "E001" and employee["departmentId"] == department["id"]
  assert employee["hiredOn"] == "2025-01-01" and employee["isActive"] is True and employee["leftOn"] is None
  listed = client.get("/api/org/employees").json()
  assert [item["id"] for item in listed] == [employee["id"]]


def testDuplicateEmployeeNoIs409(client, loginAs):
  loginAs("hr")
  departmentId = createDepartment(client)["id"]
  createEmployee(client, departmentId)
  response = client.post("/api/org/employees", json=employeeBody(departmentId, name="李小華"))
  assert response.status_code == 409 and errorOf(response)["code"] == "DUPLICATE"


def testManagerCycleIs422(client, loginAs):
  loginAs("hr")
  departmentId = createDepartment(client)["id"]
  a = createEmployee(client, departmentId, employeeNo="A")["id"]
  b = createEmployee(client, departmentId, employeeNo="B", managerId=a)["id"]
  response = client.patch(f"/api/org/employees/{a}", json={"managerId": b})
  assert response.status_code == 422 and errorOf(response)["code"] == "MANAGER_CYCLE"


def testDepartmentCycleIs422(client, loginAs):
  loginAs("hr")
  parent = createDepartment(client)["id"]
  child = createDepartment(client, "子部門", parentId=parent)["id"]
  response = client.patch(f"/api/org/departments/{parent}", json={"parentId": child})
  assert response.status_code == 422 and errorOf(response)["code"] == "DEPARTMENT_CYCLE"


def testInvalidBodyIs422WithValidationCode(client, loginAs):
  loginAs("hr")
  response = client.post("/api/org/departments", json={})
  assert response.status_code == 422 and errorOf(response)["code"] == "VALIDATION"
  assert client.post("/api/org/departments", json={"name": "  "}).status_code == 422
  assert client.post("/api/org/employees", json={"employeeNo": "E1"}).status_code == 422


def testDeactivateEmployeeViaPatch(client, loginAs):
  loginAs("hr")
  employeeId = createEmployee(client, createDepartment(client)["id"])["id"]
  response = client.patch(f"/api/org/employees/{employeeId}", json={"isActive": False, "leftOn": "2026-03-01"})
  assert response.status_code == 200 and response.json()["isActive"] is False and response.json()["leftOn"] == "2026-03-01"
  assert client.get("/api/org/employees").json() == []
  assert [item["id"] for item in client.get("/api/org/employees", params={"includeInactive": "true"}).json()] == [employeeId]


def testPatchCanClearManager(client, loginAs):
  loginAs("hr")
  departmentId = createDepartment(client)["id"]
  a = createEmployee(client, departmentId, employeeNo="A")["id"]
  b = createEmployee(client, departmentId, employeeNo="B", managerId=a)["id"]
  assert client.patch(f"/api/org/employees/{b}", json={"managerId": None}).json()["managerId"] is None


def testPatchUnknownIdIs404(client, loginAs):
  loginAs("hr")
  response = client.patch("/api/org/employees/9999", json={"name": "x"})
  assert response.status_code == 404 and errorOf(response)["code"] == "NOT_FOUND"
  assert client.patch("/api/org/departments/9999", json={"name": "x"}).status_code == 404


def testCalendarDayPutAndDelete(client, loginAs):
  loginAs("hr")
  put = client.put("/api/org/calendarDays/2026-10-10", json={"kind": "holiday", "name": "國慶日"})
  assert put.status_code == 200 and put.json() == {"day": "2026-10-10", "kind": "holiday", "name": "國慶日"}
  client.put("/api/org/calendarDays/2026-10-17", json={"kind": "makeup_workday", "name": "補班"})
  listed = client.get("/api/org/calendarDays", params={"from": "2026-10-01", "to": "2026-10-31"}).json()
  assert [item["day"] for item in listed] == ["2026-10-10", "2026-10-17"]
  assert client.delete("/api/org/calendarDays/2026-10-10").status_code == 204
  assert client.delete("/api/org/calendarDays/2026-10-10").status_code == 404
  assert client.put("/api/org/calendarDays/2026-10-11", json={"kind": "weekend", "name": "x"}).status_code == 422
  assert client.put("/api/org/calendarDays/not-a-date", json={"kind": "holiday", "name": "x"}).status_code == 422
  assert client.get("/api/org/calendarDays").status_code == 422


def testUnauthenticatedIs401(client):
  for path in ("/api/org/departments", "/api/org/employees", "/api/org/calendarDays?from=2026-01-01&to=2026-12-31"):
    response = client.get(path)
    assert response.status_code == 401 and errorOf(response)["code"] == "UNAUTHENTICATED"
  assert client.post("/api/org/departments", json={"name": "x"}).status_code == 401
