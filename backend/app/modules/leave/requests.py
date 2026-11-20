from dataclasses import dataclass
from datetime import date, datetime

import psycopg
from psycopg import Connection

from app.infra.actor import Actor
from app.infra.db import savepoint
from app.infra.errors import AppError
from app.infra.serialize import camelizeRow
from app.modules.core.service import writeAudit
from app.modules.leave import rules, service

scopes = {"mine", "toApprove", "all"}
statuses = {"pending", "approved", "rejected", "withdrawn", "cancelled"}
requestSelect = (
  "SELECT r.id, r.employee_id, e.name AS employee_name, r.leave_type_id, t.name AS leave_type_name, r.start_at, r.end_at, "
  "r.hours, r.reason, r.status, r.decided_by, coalesce(de.name, du.email) AS decided_by_name, r.decided_at, r.decision_note, "
  "r.cancelled_by, r.cancelled_at, r.created_by, r.created_at "
  "FROM leave_requests r JOIN employees e ON e.id = r.employee_id JOIN leave_types t ON t.id = r.leave_type_id "
  "LEFT JOIN users du ON du.id = r.decided_by LEFT JOIN employees de ON de.id = du.employee_id"
)


@dataclass
class LeaveInput:
  leaveTypeId: int
  startAt: datetime
  endAt: datetime
  reason: str = ""
  acknowledgeWarnings: bool = False


def loadRequest(conn: Connection, requestId: int) -> dict:
  row = conn.execute(f"{requestSelect} WHERE r.id = %s", (requestId,)).fetchone()
  if row is None:
    raise AppError("NOT_FOUND", "找不到請假申請", 404)
  return camelizeRow(row)


def calendarKindsBetween(conn: Connection, startDay: date, endDay: date) -> dict[date, str]:
  rows = conn.execute("SELECT day, kind FROM calendar_days WHERE day BETWEEN %s AND %s", (startDay, endDay)).fetchall()
  return {row["day"]: row["kind"] for row in rows}


def findMeetingConflicts(conn: Connection, employeeId: int, startAt: datetime, endAt: datetime) -> list[dict]:
  rows = conn.execute(
    "SELECT b.id AS booking_id, b.title, b.start_at, b.end_at FROM booking_participants p JOIN bookings b ON b.id = p.booking_id "
    "WHERE p.employee_id = %s AND b.status = 'confirmed' AND b.start_at < %s AND b.end_at > %s ORDER BY b.start_at, b.id",
    (employeeId, endAt, startAt),
  ).fetchall()
  return camelizeRow(rows)


def evaluate(conn: Connection, actor: Actor, data: LeaveInput, lock: bool) -> dict:
  """試算與送出共用的檢查；回傳員工列、時數、送出後剩多少（不限額度時是 None）。"""
  employee = service.getEmployeeRow(conn, service.requireOwnEmployeeId(actor), lock=lock)
  if not employee["is_active"]:
    raise AppError("LEAVE_NOT_ELIGIBLE", "已離職的員工不能請假", 422)
  leaveType = service.getLeaveType(conn, data.leaveTypeId)
  if not leaveType["isActive"]:
    raise AppError("VALIDATION", "這個假別已經停用", 422, {"field": "leaveTypeId"})
  if data.endAt <= data.startAt:
    raise AppError("VALIDATION", "結束時間要晚於開始時間", 422, {"field": "endAt"})
  if data.startAt.date() < employee["hired_on"]:
    raise AppError("LEAVE_NOT_ELIGIBLE", "請假不能早於到職日", 422)
  kinds = calendarKindsBetween(conn, data.startAt.date(), data.endAt.date())
  hours = rules.countLeaveHours(data.startAt, data.endAt, kinds)
  if hours == 0:
    raise AppError("LEAVE_NO_WORKING_HOURS", "這段時間沒有上班時間，不需要請假", 422)
  period = rules.periodForRequest(leaveType["quotaKind"], leaveType["annualCapHours"], employee["hired_on"], data.startAt, data.endAt)
  remainingAfter = None
  if period.quotaHours is not None:
    balance = service.balanceFor(conn, employee["id"], employee["hired_on"], leaveType, period.start)
    remainingAfter = balance["remainingHours"] - hours
    if remainingAfter < 0:
      raise AppError(
        "LEAVE_QUOTA_EXCEEDED", f"{leaveType['name']}只剩 {balance['remainingHours']} 小時，這次要 {hours} 小時", 422,
        {"remainingHours": balance["remainingHours"]},
      )
  return {"employee": employee, "hours": hours, "remainingAfter": remainingAfter}


def quoteRequest(conn: Connection, actor: Actor, data: LeaveInput) -> dict:
  result = evaluate(conn, actor, data, lock=False)
  conflicts = findMeetingConflicts(conn, result["employee"]["id"], data.startAt, data.endAt)
  return {"hours": result["hours"], "remainingAfter": result["remainingAfter"], "conflicts": conflicts}


def createRequest(conn: Connection, actor: Actor, data: LeaveInput, now: datetime) -> dict:
  result = evaluate(conn, actor, data, lock=True)
  employeeId = result["employee"]["id"]
  if not data.acknowledgeWarnings:
    conflicts = findMeetingConflicts(conn, employeeId, data.startAt, data.endAt)
    if conflicts:
      raise AppError("MEETING_CONFLICT", "這段時間你有會議", 409, {"conflicts": conflicts})
  reason = data.reason.strip() if isinstance(data.reason, str) else ""
  try:
    with savepoint(conn):
      requestId = conn.execute(
        "INSERT INTO leave_requests (employee_id, leave_type_id, start_at, end_at, hours, reason, created_by, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (employeeId, data.leaveTypeId, data.startAt, data.endAt, result["hours"], reason, actor.userId, now),
      ).fetchone()["id"]
  except psycopg.errors.ExclusionViolation:
    overlaps = conn.execute(
      f"{requestSelect} WHERE r.employee_id = %s AND r.status IN ('pending', 'approved') AND r.start_at < %s AND r.end_at > %s ORDER BY r.start_at",
      (employeeId, data.endAt, data.startAt),
    ).fetchall()
    raise AppError("LEAVE_OVERLAP", "這段時間已經有請假申請", 409, {"overlaps": camelizeRow(overlaps)})
  created = loadRequest(conn, requestId)
  writeAudit(conn, actor, "leave", "createLeaveRequest", "leaveRequest", requestId, None, created)
  return created


def listRequests(
  conn: Connection, actor: Actor, scope: str, status: str | None = None, start: datetime | None = None, end: datetime | None = None
) -> list[dict]:
  if scope not in scopes:
    raise AppError("VALIDATION", "scope 只能是 mine、toApprove、all", 422)
  if status is not None and status not in statuses:
    raise AppError("VALIDATION", f"status 只能是 {', '.join(sorted(statuses))}", 422)
  params = {"me": actor.employeeId, "isManager": service.isLeaveManager(actor), "status": status, "start": start, "end": end}
  joins = ""
  if scope == "mine":
    service.requireOwnEmployeeId(actor)
    condition = "r.employee_id = %(me)s"
  elif scope == "toApprove":
    joins = " LEFT JOIN employees m ON m.id = e.manager_id LEFT JOIN users mu ON mu.employee_id = m.id"
    # 主管離職、或主管沒有能登入的帳號時改由人資核准，否則這張申請沒有人看得到
    condition = (
      "r.status = 'pending' AND r.employee_id IS DISTINCT FROM %(me)s AND (e.manager_id = %(me)s "
      "OR (%(isManager)s AND (m.id IS NULL OR NOT m.is_active OR mu.id IS NULL OR NOT mu.is_active)))"
    )
  else:
    if not params["isManager"]:
      raise AppError("FORBIDDEN", "只有人資可以看所有人的請假", 403)
    condition = "true"
  rows = conn.execute(
    f"{requestSelect}{joins} WHERE {condition} AND (%(status)s::text IS NULL OR r.status = %(status)s) "
    "AND (%(start)s::timestamp IS NULL OR r.end_at > %(start)s) AND (%(end)s::timestamp IS NULL OR r.start_at < %(end)s) "
    "ORDER BY r.start_at DESC, r.id DESC",
    params,
  ).fetchall()
  return camelizeRow(rows)


def getRequest(conn: Connection, actor: Actor, requestId: int) -> dict:
  request = loadRequest(conn, requestId)
  service.requireCanView(actor, service.getEmployeeRow(conn, request["employeeId"]))
  return request
