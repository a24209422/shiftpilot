from datetime import date

import pytest

from app.infra.db import openDb
from app.infra.errors import AppError
from app.modules.core.service import listAudit
from app.modules.org import service
from tests.helpers import insertActor


def employeeData(**extra):
  data = {"employeeNo": "E001", "name": "王小明", "departmentId": None, "jobTitle": "工程師", "hiredOn": date(2025, 1, 1)}
  data.update(extra)
  return data


@pytest.fixture
def setup(migratedUrl):
  with openDb(migratedUrl) as conn:
    actor = insertActor(conn)
    department = service.createDepartment(conn, actor, "工程部")
  return migratedUrl, actor, department["id"]


def testCreateEmployeeWritesAudit(setup):
  url, actor, departmentId = setup
  with openDb(url) as conn:
    employee = service.createEmployee(conn, actor, employeeData(departmentId=departmentId))
    rows = [row for row in listAudit(conn, module="org") if row["action"] == "createEmployee"]
  assert employee["employeeNo"] == "E001" and employee["isActive"] is True and employee["hiredOn"] == "2025-01-01"
  assert len(rows) == 1
  assert rows[0]["after"]["employeeNo"] == "E001" and rows[0]["entity"] == "employee" and rows[0]["entityId"] == str(employee["id"])


def testDuplicateEmployeeNoRaisesDuplicate(setup):
  url, actor, departmentId = setup
  with openDb(url) as conn:
    service.createEmployee(conn, actor, employeeData(departmentId=departmentId))
    with pytest.raises(AppError) as info:
      service.createEmployee(conn, actor, employeeData(departmentId=departmentId, name="李小華"))
    assert (info.value.code, info.value.status) == ("DUPLICATE", 409)
    # 失敗的寫入只回復它自己，同一條連線之後還能繼續用
    assert len(service.listEmployees(conn)) == 1


def testListEmployeesHidesInactiveByDefault(setup):
  url, actor, departmentId = setup
  with openDb(url) as conn:
    employee = service.createEmployee(conn, actor, employeeData(departmentId=departmentId))
    service.updateEmployee(conn, actor, employee["id"], {"isActive": False, "leftOn": date(2026, 3, 1)})
    assert service.listEmployees(conn) == []
    listed = service.listEmployees(conn, includeInactive=True)
  assert [item["id"] for item in listed] == [employee["id"]] and listed[0]["leftOn"] == "2026-03-01"


def makeChain(conn, actor, departmentId):
  a = service.createEmployee(conn, actor, employeeData(departmentId=departmentId, employeeNo="A"))["id"]
  b = service.createEmployee(conn, actor, employeeData(departmentId=departmentId, employeeNo="B", managerId=a))["id"]
  c = service.createEmployee(conn, actor, employeeData(departmentId=departmentId, employeeNo="C", managerId=b))["id"]
  return a, b, c


def testListSubordinateIdsCoversAllLevels(setup):
  url, actor, departmentId = setup
  with openDb(url) as conn:
    a, b, c = makeChain(conn, actor, departmentId)
    assert service.listSubordinateIds(conn, a) == {b, c}
    assert service.listSubordinateIds(conn, c) == set()


def testListSubordinateIdsSurvivesCycle(setup):
  url, actor, departmentId = setup
  with openDb(url) as conn:
    a, b, _ = makeChain(conn, actor, departmentId)
    # 繞過 service 直接改資料庫，模擬資料已經壞掉的情況
    conn.execute("UPDATE employees SET manager_id = %s WHERE id = %s", (b, a))
    result = service.listSubordinateIds(conn, a)
  assert a not in result and b in result


def testManagerCycleIsRejected(setup):
  url, actor, departmentId = setup
  with openDb(url) as conn:
    a, b, c = makeChain(conn, actor, departmentId)
    with pytest.raises(AppError) as info:
      service.updateEmployee(conn, actor, a, {"managerId": c})
    assert (info.value.code, info.value.status) == ("MANAGER_CYCLE", 422)
    with pytest.raises(AppError) as selfInfo:
      service.updateEmployee(conn, actor, a, {"managerId": a})
    assert selfInfo.value.code == "MANAGER_CYCLE"


def testDepartmentCycleIsRejected(setup):
  url, actor, departmentId = setup
  with openDb(url) as conn:
    child = service.createDepartment(conn, actor, "子部門", departmentId)["id"]
    with pytest.raises(AppError) as info:
      service.updateDepartment(conn, actor, departmentId, {"parentId": child})
    assert (info.value.code, info.value.status) == ("DEPARTMENT_CYCLE", 422)


def testUpdateDepartmentRenamesAndReparents(setup):
  url, actor, departmentId = setup
  with openDb(url) as conn:
    other = service.createDepartment(conn, actor, "營運部")["id"]
    updated = service.updateDepartment(conn, actor, other, {"name": "營運一部", "parentId": departmentId})
    assert (updated["name"], updated["parentId"]) == ("營運一部", departmentId)
    assert [item["name"] for item in service.listDepartments(conn)] == ["工程部", "營運一部"]


def testUpsertCalendarDayReplacesExisting(setup):
  url, actor, _ = setup
  with openDb(url) as conn:
    service.upsertCalendarDay(conn, actor, date(2026, 10, 10), "holiday", "國慶日")
    service.upsertCalendarDay(conn, actor, date(2026, 10, 10), "makeup_workday", "補班")
    days = service.listCalendarDays(conn, date(2026, 10, 1), date(2026, 10, 31))
    assert [(item["day"], item["kind"], item["name"]) for item in days] == [("2026-10-10", "makeup_workday", "補班")]
    service.deleteCalendarDay(conn, actor, date(2026, 10, 10))
    assert service.listCalendarDays(conn, date(2026, 10, 1), date(2026, 10, 31)) == []
    with pytest.raises(AppError) as info:
      service.deleteCalendarDay(conn, actor, date(2026, 10, 10))
    assert info.value.code == "NOT_FOUND"


def testCalendarDayRejectsUnknownKind(setup):
  url, actor, _ = setup
  with openDb(url) as conn:
    with pytest.raises(AppError) as info:
      service.upsertCalendarDay(conn, actor, date(2026, 10, 10), "weekend", "週末")
  assert (info.value.code, info.value.status) == ("VALIDATION", 422)


def testBlankNameIsValidationError(setup):
  url, actor, departmentId = setup
  with openDb(url) as conn:
    with pytest.raises(AppError) as info:
      service.createDepartment(conn, actor, "   ")
    assert (info.value.code, info.value.status) == ("VALIDATION", 422)
    with pytest.raises(AppError) as employeeInfo:
      service.createEmployee(conn, actor, employeeData(departmentId=departmentId, name=" "))
    assert employeeInfo.value.code == "VALIDATION"


def testUnknownDepartmentAndUnknownFieldAreValidationErrors(setup):
  url, actor, departmentId = setup
  with openDb(url) as conn:
    with pytest.raises(AppError) as missing:
      service.createEmployee(conn, actor, employeeData(departmentId=9999))
    assert missing.value.code == "VALIDATION"
    employee = service.createEmployee(conn, actor, employeeData(departmentId=departmentId))
    with pytest.raises(AppError) as unknown:
      service.updateEmployee(conn, actor, employee["id"], {"salary": 100})
    assert unknown.value.code == "VALIDATION"


def testGetEmployeeAndUpdateMissingAreNotFound(setup):
  url, actor, _ = setup
  with openDb(url) as conn:
    with pytest.raises(AppError) as getInfo:
      service.getEmployee(conn, 9999)
    assert (getInfo.value.code, getInfo.value.status) == ("NOT_FOUND", 404)
    with pytest.raises(AppError) as updateInfo:
      service.updateDepartment(conn, actor, 9999, {"name": "x"})
    assert updateInfo.value.code == "NOT_FOUND"
