from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.infra.actor import Actor
from app.infra.http import connDependency, requirePermission
from app.infra.serialize import parseLocalTime
from app.modules.booking import service
from app.modules.booking.service import BookingInput

router = APIRouter()

readBooking = requirePermission("booking.read")
writeBooking = requirePermission("booking.write")
manageResources = requirePermission("booking.resources.manage")


class ResourceCreate(BaseModel):
  name: str
  kind: str
  location: str | None = None
  capacity: int | None = None
  features: list[str] = []
  note: str | None = None


class ResourceUpdate(BaseModel):
  name: str | None = None
  kind: str | None = None
  location: str | None = None
  capacity: int | None = None
  features: list[str] | None = None
  isActive: bool | None = None
  note: str | None = None


# 時間用字串收進來、自己解析：含時區位移的輸入要明確拒絕，不能讓 pydantic 悄悄換算
class BookingCreate(BaseModel):
  title: str
  category: str
  startAt: str
  endAt: str
  resourceIds: list[int] = []
  participantEmployeeIds: list[int] = []
  organizerEmployeeId: int | None = None
  note: str | None = None
  acknowledgeWarnings: bool = False


class BookingUpdate(BaseModel):
  title: str | None = None
  category: str | None = None
  startAt: str | None = None
  endAt: str | None = None
  resourceIds: list[int] | None = None
  participantEmployeeIds: list[int] | None = None
  organizerEmployeeId: int | None = None
  note: str | None = None
  acknowledgeWarnings: bool | None = None


@router.get("/resources")
def listResources(includeInactive: bool = False, actor: Actor = Depends(readBooking), conn=connDependency):
  return service.listResources(conn, includeInactive)


@router.post("/resources", status_code=201)
def createResource(body: ResourceCreate, actor: Actor = Depends(manageResources), conn=connDependency):
  return service.createResource(conn, actor, body.model_dump())


@router.patch("/resources/{resourceId}")
def updateResource(resourceId: int, body: ResourceUpdate, actor: Actor = Depends(manageResources), conn=connDependency):
  return service.updateResource(conn, actor, resourceId, body.model_dump(exclude_unset=True))


@router.get("/bookings")
def listBookings(
  start: str = Query(alias="from"),
  end: str = Query(alias="to"),
  resourceId: int | None = None,
  employeeId: int | None = None,
  includeCancelled: bool = False,
  actor: Actor = Depends(readBooking),
  conn=connDependency,
):
  return service.listBookings(conn, parseLocalTime(start), parseLocalTime(end), resourceId, employeeId, includeCancelled)


@router.post("/bookings", status_code=201)
def createBooking(body: BookingCreate, actor: Actor = Depends(writeBooking), conn=connDependency):
  data = BookingInput(
    title=body.title,
    category=body.category,
    startAt=parseLocalTime(body.startAt),
    endAt=parseLocalTime(body.endAt),
    resourceIds=body.resourceIds,
    participantEmployeeIds=body.participantEmployeeIds,
    organizerEmployeeId=body.organizerEmployeeId,
    note=body.note,
    acknowledgeWarnings=body.acknowledgeWarnings,
  )
  return service.createBooking(conn, actor, data)


@router.patch("/bookings/{bookingId}")
def updateBooking(bookingId: int, body: BookingUpdate, actor: Actor = Depends(writeBooking), conn=connDependency):
  fields = body.model_dump(exclude_unset=True)
  for key in ("startAt", "endAt"):
    if fields.get(key) is not None:
      fields[key] = parseLocalTime(fields[key])
  return service.updateBooking(conn, actor, bookingId, fields)


@router.post("/bookings/{bookingId}/cancel")
def cancelBooking(bookingId: int, actor: Actor = Depends(writeBooking), conn=connDependency):
  return service.cancelBooking(conn, actor, bookingId)


@router.get("/summary")
def getSummary(actor: Actor = Depends(readBooking), conn=connDependency):
  return service.getSummary(conn, datetime.now(), actor.employeeId)
