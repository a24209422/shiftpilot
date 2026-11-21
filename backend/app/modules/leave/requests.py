from dataclasses import dataclass
from datetime import datetime, timedelta

import psycopg
from psycopg import Connection

from app.infra.actor import Actor
from app.infra.db import savepoint
from app.infra.errors import AppError
from app.infra.serialize import camelizeRow
from app.infra.validate import requireText
from app.modules.core.service import writeAudit
from app.modules.leave import rules, service
from app.modules.shift import rules as shiftRules, service as shiftService

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
  # 先做便宜的檢查：年度檢查會把範圍限在一年內，避免超長區間在持有員工列鎖時逐日跑迴圈
  rules.requireWholeHour(data.startAt, "startAt")
  rules.requireWholeHour(data.endAt, "endAt")
  period = rules.periodForRequest(leaveType["quotaKind"], leaveType["annualCapHours"], employee["hired_on"], data.startAt, data.endAt)
  # 時數依這個人的班計算；班的推算（含假日、補班日）由排班模組負責
  windows = shiftService.workWindows(conn, [employee["id"]], data.startAt, data.endAt)[employee["id"]]
  hours = rules.countLeaveHours(data.startAt, data.endAt, windows)
  if hours == 0:
    raise AppError("LEAVE_NO_WORKING_HOURS", "這段時間沒有上班時間，不需要請假", 422)
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


# ---------- 狀態變更 ----------


def lockForDecision(conn: Connection, requestId: int) -> tuple[dict, dict]:
  # 先鎖員工、再鎖申請，跟送出申請的順序一樣，兩邊同時進行時不會互相等待而死結
  employeeId = loadRequest(conn, requestId)["employeeId"]
  employee = service.getEmployeeRow(conn, employeeId, lock=True)
  conn.execute("SELECT id FROM leave_requests WHERE id = %s FOR UPDATE", (requestId,))
  return loadRequest(conn, requestId), employee


def requireStatus(request: dict, status: str, message: str) -> None:
  if request["status"] != status:
    raise AppError("LEAVE_INVALID_STATE", message, 409, {"status": request["status"]})


def requireApprover(conn: Connection, actor: Actor, request: dict) -> None:
  if actor.employeeId is not None and actor.employeeId == request["employeeId"]:
    raise AppError("FORBIDDEN", "不能核准自己的請假", 403)
  if service.isLeaveManager(actor):
    return
  employee = service.getEmployeeRow(conn, request["employeeId"])
  if actor.employeeId is not None and employee["manager_id"] == actor.employeeId:
    return
  raise AppError("FORBIDDEN", "只有直屬主管或人資可以核准這張申請", 403)


def approveRequest(conn: Connection, actor: Actor, requestId: int, note: str | None, now: datetime) -> dict:
  before, employee = lockForDecision(conn, requestId)
  requireApprover(conn, actor, before)
  requireStatus(before, "pending", "只有待核准的申請可以核准")
  leaveType = service.getLeaveType(conn, before["leaveTypeId"])
  startDay = datetime.fromisoformat(before["startAt"]).date()
  balance = service.balanceFor(conn, employee["id"], employee["hired_on"], leaveType, startDay)
  # 送出後人資可能調低了額度；這張本身已經算在待核准裡，剩餘小於 0 才是不夠
  if balance["remainingHours"] is not None and balance["remainingHours"] < 0:
    raise AppError(
      "LEAVE_QUOTA_EXCEEDED", f"{leaveType['name']}的額度已經不夠，差 {-balance['remainingHours']} 小時", 422,
      {"remainingHours": balance["remainingHours"]},
    )
  conn.execute(
    "UPDATE leave_requests SET status = 'approved', decided_by = %s, decided_at = %s, decision_note = %s WHERE id = %s",
    (actor.userId, now, (note or "").strip() or None, requestId),
  )
  after = loadRequest(conn, requestId)
  writeAudit(conn, actor, "leave", "approveLeaveRequest", "leaveRequest", requestId, before, after)
  return after


def rejectRequest(conn: Connection, actor: Actor, requestId: int, note: str | None, now: datetime) -> dict:
  before, _ = lockForDecision(conn, requestId)
  requireApprover(conn, actor, before)
  requireStatus(before, "pending", "只有待核准的申請可以退回")
  reason = requireText(note, "退回理由")
  conn.execute(
    "UPDATE leave_requests SET status = 'rejected', decided_by = %s, decided_at = %s, decision_note = %s WHERE id = %s",
    (actor.userId, now, reason, requestId),
  )
  after = loadRequest(conn, requestId)
  writeAudit(conn, actor, "leave", "rejectLeaveRequest", "leaveRequest", requestId, before, after)
  return after


def withdrawRequest(conn: Connection, actor: Actor, requestId: int, now: datetime) -> dict:
  before, _ = lockForDecision(conn, requestId)
  if actor.employeeId is None or actor.employeeId != before["employeeId"]:
    raise AppError("FORBIDDEN", "只有申請人可以撤回", 403)
  requireStatus(before, "pending", "只有待核准的申請可以撤回")
  conn.execute(
    "UPDATE leave_requests SET status = 'withdrawn', cancelled_by = %s, cancelled_at = %s WHERE id = %s", (actor.userId, now, requestId)
  )
  after = loadRequest(conn, requestId)
  writeAudit(conn, actor, "leave", "withdrawLeaveRequest", "leaveRequest", requestId, before, after)
  return after


def cancelRequest(conn: Connection, actor: Actor, requestId: int, now: datetime) -> dict:
  before, _ = lockForDecision(conn, requestId)
  isOwner = actor.employeeId is not None and actor.employeeId == before["employeeId"]
  isManager = service.isLeaveManager(actor)
  if not (isOwner or isManager):
    raise AppError("FORBIDDEN", "只有申請人或人資可以取消", 403)
  requireStatus(before, "approved", "只有已核准的請假可以取消")
  # 假已經開始或結束，可能牽涉薪資與出勤，交給人資處理
  if not isManager and datetime.fromisoformat(before["startAt"]) <= now:
    raise AppError("FORBIDDEN", "假已經開始，請找人資取消", 403)
  conn.execute(
    "UPDATE leave_requests SET status = 'cancelled', cancelled_by = %s, cancelled_at = %s WHERE id = %s", (actor.userId, now, requestId)
  )
  after = loadRequest(conn, requestId)
  writeAudit(conn, actor, "leave", "cancelLeaveRequest", "leaveRequest", requestId, before, after)
  return after


# ---------- 給時間軸與資源預約 ----------


def listCalendar(conn: Connection, actor: Actor, start: datetime, end: datetime) -> list[dict]:
  if end <= start or end - start > timedelta(days=31):
    raise AppError("VALIDATION", "查詢區間要大於 0、最多 31 天", 422)
  rows = conn.execute(
    "SELECT r.id, r.employee_id, r.start_at, r.end_at, r.status, t.name AS leave_type_name, e.manager_id "
    "FROM leave_requests r JOIN employees e ON e.id = r.employee_id JOIN leave_types t ON t.id = r.leave_type_id "
    "WHERE r.status IN ('pending', 'approved') AND r.start_at < %s AND r.end_at > %s ORDER BY r.start_at, r.id",
    (end, start),
  ).fetchall()
  windowsByEmployee = shiftService.workWindows(conn, sorted({row["employee_id"] for row in rows}), start, end)
  isManager = service.isLeaveManager(actor)
  result = []
  for row in rows:
    managerId = row.pop("manager_id")
    # 前端直接畫這些片段，不用自己猜上班時間
    row["segments"] = [
      {"startAt": segmentStart, "endAt": segmentEnd}
      for segmentStart, segmentEnd in shiftRules.clipWindows(windowsByEmployee[row["employee_id"]], row["start_at"], row["end_at"])
    ]
    # 假別是私人資訊：只有本人、直屬主管、人資看得到，其他人只知道這段時間不在
    if not (isManager or (actor.employeeId is not None and actor.employeeId in (row["employee_id"], managerId))):
      row["leave_type_name"] = None
    result.append(row)
  return camelizeRow(result)


def findUnavailability(conn: Connection, employeeIds: list[int], startAt: datetime, endAt: datetime) -> list[dict]:
  rows = conn.execute(
    "SELECT employee_id, status, start_at, end_at FROM leave_requests WHERE employee_id = ANY(%s) "
    "AND status IN ('pending', 'approved') AND start_at < %s AND end_at > %s ORDER BY start_at, id",
    (employeeIds, endAt, startAt),
  ).fetchall()
  # 不帶假別：排會議的人不一定有權限知道別人請的是什麼假
  return camelizeRow([
    {"employeeId": row["employee_id"], "reason": "請假" if row["status"] == "approved" else "請假（待核准）",
     "startAt": row["start_at"], "endAt": row["end_at"]}
    for row in rows
  ])
