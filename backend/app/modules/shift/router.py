from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.infra.actor import Actor
from app.infra.errors import AppError
from app.infra.http import connDependency, requirePermission
from app.infra.permissions import hasPermission
from app.infra.registry import registerUnavailabilityProvider
from app.modules.shift import service

router = APIRouter()

readShift = requirePermission("shift.read")
manageShift = requirePermission("shift.manage")


def onAppCreated() -> None:
  # 每次建立 app 都登記一次：測試會清空登記表，只在匯入時登記的話，清空後就消失了
  registerUnavailabilityProvider("shift", service.findUnavailability)


class ShiftTypeCreate(BaseModel):
  code: str
  name: str
  startTime: str
  endTime: str
  breakStart: str | None = None
  breakEnd: str | None = None
  isDefault: bool = False


# 不能改的欄位也收進來，才能回清楚的錯誤；pydantic 預設會默默丟掉不認得的欄位
class ShiftTypeUpdate(BaseModel):
  name: str | None = None
  isActive: bool | None = None
  isDefault: bool | None = None
  code: str | None = None
  startTime: str | None = None
  endTime: str | None = None
  breakStart: str | None = None
  breakEnd: str | None = None


class RosterDay(BaseModel):
  weekday: int
  shiftTypeId: int


class RosterCreate(BaseModel):
  employeeId: int
  effectiveFrom: date
  days: list[RosterDay]


class OverrideBody(BaseModel):
  employeeId: int
  day: date
  shiftTypeId: int | None = None
  note: str = ""


def parseEmployeeIds(text: str | None) -> list[int] | None:
  if not text:
    return None
  try:
    return [int(part) for part in text.split(",") if part.strip()]
  except ValueError:
    raise AppError("VALIDATION", "employeeIds 要是逗號分隔的數字", 422, {"field": "employeeIds"})


@router.get("/types")
def listTypes(includeInactive: bool = False, actor: Actor = Depends(readShift), conn=connDependency):
  if includeInactive and not hasPermission(actor.role, "shift.manage"):
    raise AppError("FORBIDDEN", "沒有權限執行這個動作", 403)
  return service.listShiftTypes(conn, includeInactive)


@router.post("/types", status_code=201)
def createType(body: ShiftTypeCreate, actor: Actor = Depends(manageShift), conn=connDependency):
  return service.createShiftType(conn, actor, body.model_dump())


@router.patch("/types/{shiftTypeId}")
def updateType(shiftTypeId: int, body: ShiftTypeUpdate, actor: Actor = Depends(manageShift), conn=connDependency):
  return service.updateShiftType(conn, actor, shiftTypeId, body.model_dump(exclude_unset=True))


@router.get("/rosters")
def listRosters(employeeId: int, actor: Actor = Depends(readShift), conn=connDependency):
  return service.listRosters(conn, employeeId)


@router.post("/rosters", status_code=201)
def createRoster(body: RosterCreate, actor: Actor = Depends(readShift), conn=connDependency):
  return service.createRoster(conn, actor, body.model_dump(), datetime.now())


@router.delete("/rosters/{rosterId}", status_code=204)
def deleteRoster(rosterId: int, actor: Actor = Depends(readShift), conn=connDependency):
  service.deleteRoster(conn, actor, rosterId, date.today())


@router.get("/overrides")
def listOverrides(
  employeeId: int, start: date = Query(alias="from"), end: date = Query(alias="to"),
  actor: Actor = Depends(readShift), conn=connDependency,
):
  return service.listOverrides(conn, employeeId, start, end)


@router.put("/overrides")
def upsertOverride(body: OverrideBody, actor: Actor = Depends(readShift), conn=connDependency):
  return service.upsertOverride(conn, actor, body.model_dump(), datetime.now())


@router.delete("/overrides/{employeeId}/{day}", status_code=204)
def deleteOverride(employeeId: int, day: date, actor: Actor = Depends(readShift), conn=connDependency):
  service.deleteOverride(conn, actor, employeeId, day, date.today())


@router.get("/schedule")
def getSchedule(
  start: date = Query(alias="from"), end: date = Query(alias="to"), employeeIds: str | None = None,
  actor: Actor = Depends(readShift), conn=connDependency,
):
  return service.getSchedule(conn, parseEmployeeIds(employeeIds), start, end)
