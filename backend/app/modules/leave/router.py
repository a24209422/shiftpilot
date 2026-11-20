from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.infra.actor import Actor
from app.infra.errors import AppError
from app.infra.http import connDependency, requirePermission
from app.infra.registry import registerUnavailabilityProvider
from app.infra.serialize import parseLocalTime
from app.modules.leave import requests, service

router = APIRouter()

requestLeave = requirePermission("leave.request")
manageLeave = requirePermission("leave.manage")


def onAppCreated() -> None:
  # 每次建立 app 都登記一次：測試會清空登記表，只在匯入時登記的話，清空後就消失了
  registerUnavailabilityProvider("leave", requests.findUnavailability)


class LeaveTypeCreate(BaseModel):
  code: str
  name: str
  paidRatio: float
  quotaKind: str
  annualCapHours: int | None = None


# code、quotaKind 收進來是為了回清楚的錯誤；pydantic 預設會默默丟掉不認得的欄位
class LeaveTypeUpdate(BaseModel):
  name: str | None = None
  paidRatio: float | None = None
  annualCapHours: int | None = None
  isActive: bool | None = None
  code: str | None = None
  quotaKind: str | None = None


# 時間用字串收進來、自己解析：含時區位移的輸入要明確拒絕，不能讓 pydantic 悄悄換算
class LeaveRequestBody(BaseModel):
  leaveTypeId: int
  startAt: str
  endAt: str
  reason: str = ""
  acknowledgeWarnings: bool = False


class DecisionBody(BaseModel):
  note: str | None = None


class AdjustmentCreate(BaseModel):
  employeeId: int
  leaveTypeId: int
  periodStart: date
  hours: int
  reason: str


def toInput(body: LeaveRequestBody) -> requests.LeaveInput:
  return requests.LeaveInput(
    body.leaveTypeId, parseLocalTime(body.startAt), parseLocalTime(body.endAt), body.reason, body.acknowledgeWarnings
  )


@router.get("/types")
def listTypes(includeInactive: bool = False, actor: Actor = Depends(requestLeave), conn=connDependency):
  if includeInactive and not service.isLeaveManager(actor):
    raise AppError("FORBIDDEN", "沒有權限執行這個動作", 403)
  return service.listLeaveTypes(conn, includeInactive)


@router.post("/types", status_code=201)
def createType(body: LeaveTypeCreate, actor: Actor = Depends(manageLeave), conn=connDependency):
  return service.createLeaveType(conn, actor, body.model_dump())


@router.patch("/types/{leaveTypeId}")
def updateType(leaveTypeId: int, body: LeaveTypeUpdate, actor: Actor = Depends(manageLeave), conn=connDependency):
  return service.updateLeaveType(conn, actor, leaveTypeId, body.model_dump(exclude_unset=True))


@router.get("/balances")
def getBalances(employeeId: int | None = None, on: date | None = None, actor: Actor = Depends(requestLeave), conn=connDependency):
  return service.getBalances(conn, actor, employeeId, on or date.today())


@router.post("/requests/quote")
def quoteRequest(body: LeaveRequestBody, actor: Actor = Depends(requestLeave), conn=connDependency):
  return requests.quoteRequest(conn, actor, toInput(body))


@router.post("/requests", status_code=201)
def createRequest(body: LeaveRequestBody, actor: Actor = Depends(requestLeave), conn=connDependency):
  return requests.createRequest(conn, actor, toInput(body), datetime.now())


@router.get("/requests")
def listRequests(
  scope: str = "mine",
  status: str | None = None,
  start: str | None = Query(default=None, alias="from"),
  end: str | None = Query(default=None, alias="to"),
  actor: Actor = Depends(requestLeave),
  conn=connDependency,
):
  return requests.listRequests(
    conn, actor, scope, status, parseLocalTime(start) if start else None, parseLocalTime(end) if end else None
  )


@router.get("/requests/{requestId}")
def getRequest(requestId: int, actor: Actor = Depends(requestLeave), conn=connDependency):
  return requests.getRequest(conn, actor, requestId)


@router.post("/requests/{requestId}/approve")
def approveRequest(requestId: int, body: DecisionBody, actor: Actor = Depends(requestLeave), conn=connDependency):
  return requests.approveRequest(conn, actor, requestId, body.note, datetime.now())


@router.post("/requests/{requestId}/reject")
def rejectRequest(requestId: int, body: DecisionBody, actor: Actor = Depends(requestLeave), conn=connDependency):
  return requests.rejectRequest(conn, actor, requestId, body.note, datetime.now())


@router.post("/requests/{requestId}/withdraw")
def withdrawRequest(requestId: int, actor: Actor = Depends(requestLeave), conn=connDependency):
  return requests.withdrawRequest(conn, actor, requestId, datetime.now())


@router.post("/requests/{requestId}/cancel")
def cancelRequest(requestId: int, actor: Actor = Depends(requestLeave), conn=connDependency):
  return requests.cancelRequest(conn, actor, requestId, datetime.now())


@router.get("/adjustments")
def listAdjustments(employeeId: int, actor: Actor = Depends(manageLeave), conn=connDependency):
  return service.listAdjustments(conn, employeeId)


@router.post("/adjustments", status_code=201)
def createAdjustment(body: AdjustmentCreate, actor: Actor = Depends(manageLeave), conn=connDependency):
  return service.createAdjustment(conn, actor, body.model_dump(), datetime.now())


@router.get("/unused")
def listUnused(periodEndFrom: date, periodEndTo: date, actor: Actor = Depends(manageLeave), conn=connDependency):
  return service.listUnused(conn, periodEndFrom, periodEndTo)


@router.get("/calendar")
def listCalendar(
  start: str = Query(alias="from"), end: str = Query(alias="to"), actor: Actor = Depends(requestLeave), conn=connDependency
):
  return requests.listCalendar(conn, actor, parseLocalTime(start), parseLocalTime(end))
