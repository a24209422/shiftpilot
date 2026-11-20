from datetime import date

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel

from app.infra.actor import Actor
from app.infra.http import connDependency, requirePermission
from app.modules.org import service

router = APIRouter()

readOrg = requirePermission("org.read")
manageOrg = requirePermission("org.manage")


class DepartmentCreate(BaseModel):
  name: str
  parentId: int | None = None


class DepartmentUpdate(BaseModel):
  name: str | None = None
  parentId: int | None = None


class EmployeeCreate(BaseModel):
  employeeNo: str
  name: str
  email: str | None = None
  departmentId: int
  jobTitle: str
  managerId: int | None = None
  hiredOn: date


class EmployeeUpdate(BaseModel):
  employeeNo: str | None = None
  name: str | None = None
  email: str | None = None
  departmentId: int | None = None
  jobTitle: str | None = None
  managerId: int | None = None
  hiredOn: date | None = None
  isActive: bool | None = None
  leftOn: date | None = None


class CalendarDayBody(BaseModel):
  kind: str
  name: str


@router.get("/departments")
def listDepartments(actor: Actor = Depends(readOrg), conn=connDependency):
  return service.listDepartments(conn)


@router.post("/departments", status_code=201)
def createDepartment(body: DepartmentCreate, actor: Actor = Depends(manageOrg), conn=connDependency):
  return service.createDepartment(conn, actor, body.name, body.parentId)


@router.patch("/departments/{departmentId}")
def updateDepartment(departmentId: int, body: DepartmentUpdate, actor: Actor = Depends(manageOrg), conn=connDependency):
  # exclude_unset：只改請求裡有寫的欄位，明確寫 null 才是「清空」
  return service.updateDepartment(conn, actor, departmentId, body.model_dump(exclude_unset=True))


@router.get("/employees")
def listEmployees(includeInactive: bool = False, actor: Actor = Depends(readOrg), conn=connDependency):
  return service.listEmployees(conn, includeInactive)


@router.post("/employees", status_code=201)
def createEmployee(body: EmployeeCreate, actor: Actor = Depends(manageOrg), conn=connDependency):
  return service.createEmployee(conn, actor, body.model_dump())


@router.patch("/employees/{employeeId}")
def updateEmployee(employeeId: int, body: EmployeeUpdate, actor: Actor = Depends(manageOrg), conn=connDependency):
  return service.updateEmployee(conn, actor, employeeId, body.model_dump(exclude_unset=True))


@router.get("/calendarDays")
def listCalendarDays(
  start: date = Query(alias="from"), end: date = Query(alias="to"), actor: Actor = Depends(readOrg), conn=connDependency
):
  return service.listCalendarDays(conn, start, end)


@router.put("/calendarDays/{day}")
def putCalendarDay(day: date, body: CalendarDayBody, actor: Actor = Depends(manageOrg), conn=connDependency):
  return service.upsertCalendarDay(conn, actor, day, body.kind, body.name)


@router.delete("/calendarDays/{day}", status_code=204)
def deleteCalendarDay(day: date, actor: Actor = Depends(manageOrg), conn=connDependency):
  service.deleteCalendarDay(conn, actor, day)
  return Response(status_code=204)
