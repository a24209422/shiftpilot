from datetime import date, datetime, timedelta

from psycopg import Connection

from app.infra.actor import Actor
from app.infra.db import mapDbErrors
from app.infra.errors import AppError
from app.infra.permissions import hasPermission
from app.infra.serialize import camelizeRow
from app.infra.validate import requireText
from app.modules.core.service import writeAudit
from app.modules.leave import rules

# numeric 轉成 float：Decimal 在 JSON 與比較時都不好用，比例只有 0、0.5、1 這種值
typeColumns = "id, code, name, paid_ratio::float8 AS paid_ratio, quota_kind, annual_cap_hours, is_active"
quotaKinds = {"seniority", "yearly_cap", "none"}
typeCreateFields = {"code", "name", "paidRatio", "quotaKind", "annualCapHours"}
typeUpdateFields = {"name": "name", "paidRatio": "paid_ratio", "annualCapHours": "annual_cap_hours", "isActive": "is_active"}
adjustmentSelect = (
  "SELECT a.id, a.employee_id, a.leave_type_id, t.name AS leave_type_name, a.period_start, a.hours, a.reason, "
  "a.created_by, u.email AS created_by_email, a.created_at "
  "FROM leave_adjustments a JOIN leave_types t ON t.id = a.leave_type_id JOIN users u ON u.id = a.created_by"
)


# ---------- 身分與存取 ----------


def isLeaveManager(actor: Actor) -> bool:
  return hasPermission(actor.role, "leave.manage")


def requireOwnEmployeeId(actor: Actor) -> int:
  if actor.employeeId is None:
    raise AppError("NO_EMPLOYEE", "這個帳號沒有對應的員工，不能請假", 422)
  return actor.employeeId


def getEmployeeRow(conn: Connection, employeeId: int, lock: bool = False) -> dict:
  # lock：同一個人的送出與核准排隊檢查額度，兩張同時送出不會都通過
  suffix = " FOR UPDATE" if lock else ""
  row = conn.execute(
    f"SELECT id, name, manager_id, hired_on, is_active FROM employees WHERE id = %s{suffix}", (employeeId,)
  ).fetchone()
  if row is None:
    raise AppError("NOT_FOUND", "找不到員工", 404)
  return row


def requireCanView(actor: Actor, employee: dict) -> None:
  if isLeaveManager(actor):
    return
  if actor.employeeId is not None and actor.employeeId in (employee["id"], employee["manager_id"]):
    return
  raise AppError("FORBIDDEN", "只能看自己與直屬下屬的請假資料", 403)


# ---------- 假別 ----------


def listLeaveTypes(conn: Connection, includeInactive: bool = False) -> list[dict]:
  where = "" if includeInactive else "WHERE is_active"
  return camelizeRow(conn.execute(f"SELECT {typeColumns} FROM leave_types {where} ORDER BY id").fetchall())


def getLeaveType(conn: Connection, leaveTypeId: int) -> dict:
  row = conn.execute(f"SELECT {typeColumns} FROM leave_types WHERE id = %s", (leaveTypeId,)).fetchone()
  if row is None:
    raise AppError("NOT_FOUND", "找不到假別", 404)
  return camelizeRow(row)


def createLeaveType(conn: Connection, actor: Actor, data: dict) -> dict:
  unknown = set(data) - typeCreateFields
  if unknown:
    raise AppError("VALIDATION", f"不能設定的欄位：{', '.join(sorted(unknown))}", 422)
  code = requireText(data.get("code"), "代碼")
  name = requireText(data.get("name"), "名稱")
  if data.get("quotaKind") not in quotaKinds:
    raise AppError("VALIDATION", "quotaKind 只能是 none、seniority、yearly_cap", 422, {"field": "quotaKind"})
  with mapDbErrors(conn):
    row = conn.execute(
      f"INSERT INTO leave_types (code, name, paid_ratio, quota_kind, annual_cap_hours) VALUES (%s, %s, %s, %s, %s) RETURNING {typeColumns}",
      (code, name, data.get("paidRatio"), data["quotaKind"], data.get("annualCapHours")),
    ).fetchone()
  leaveType = camelizeRow(row)
  writeAudit(conn, actor, "leave", "createLeaveType", "leaveType", leaveType["id"], None, leaveType)
  return leaveType


def updateLeaveType(conn: Connection, actor: Actor, leaveTypeId: int, fields: dict) -> dict:
  for frozen in ("quotaKind", "code"):
    # 額度類型一改，舊申請的年度算法就跟著變；代碼是給程式辨認的
    if frozen in fields:
      raise AppError("VALIDATION", "代碼與額度類型建立後不能修改", 422, {"field": frozen})
  unknown = set(fields) - set(typeUpdateFields)
  if unknown:
    raise AppError("VALIDATION", f"不能修改的欄位：{', '.join(sorted(unknown))}", 422)
  if "name" in fields:
    fields = {**fields, "name": requireText(fields["name"], "名稱")}
  before = getLeaveType(conn, leaveTypeId)
  if not fields:
    return before
  assignments = ", ".join(f"{typeUpdateFields[key]} = %s" for key in fields)
  with mapDbErrors(conn):
    conn.execute(f"UPDATE leave_types SET {assignments} WHERE id = %s", [*fields.values(), leaveTypeId])
  after = getLeaveType(conn, leaveTypeId)
  writeAudit(conn, actor, "leave", "updateLeaveType", "leaveType", leaveTypeId, before, after)
  return after


# ---------- 餘額 ----------


def balanceFor(conn: Connection, employeeId: int, hiredOn: date, leaveType: dict, day: date) -> dict:
  result = {
    "leaveTypeId": leaveType["id"], "leaveTypeName": leaveType["name"], "quotaKind": leaveType["quotaKind"],
    "periodStart": None, "periodEnd": None, "quotaHours": 0, "adjustmentHours": 0,
    "approvedHours": 0, "pendingHours": 0, "remainingHours": 0,
  }
  period = rules.periodFor(leaveType["quotaKind"], leaveType["annualCapHours"], hiredOn, day)
  if period is None:
    return result
  # 申請不會跨年度，所以用開始時間判斷屬於哪個年度就夠了
  used = {
    row["status"]: row["hours"]
    for row in conn.execute(
      "SELECT status, sum(hours)::int AS hours FROM leave_requests WHERE employee_id = %s AND leave_type_id = %s "
      "AND status IN ('pending', 'approved') AND start_at >= %s AND start_at < %s GROUP BY status",
      (employeeId, leaveType["id"], period.start, period.end + timedelta(days=1)),
    ).fetchall()
  }
  adjustment = conn.execute(
    "SELECT coalesce(sum(hours), 0)::int AS hours FROM leave_adjustments WHERE employee_id = %s AND leave_type_id = %s AND period_start = %s",
    (employeeId, leaveType["id"], period.start),
  ).fetchone()["hours"]
  approved = used.get("approved", 0)
  pending = used.get("pending", 0)
  # 待核准的也先扣：不然同時送好幾張，每張單獨看都沒超過上限
  remaining = None if period.quotaHours is None else period.quotaHours + adjustment - approved - pending
  result.update(
    periodStart=period.start.isoformat(), periodEnd=period.end.isoformat(), quotaHours=period.quotaHours,
    adjustmentHours=adjustment, approvedHours=approved, pendingHours=pending, remainingHours=remaining,
  )
  return result


def getBalances(conn: Connection, actor: Actor, employeeId: int | None, day: date) -> list[dict]:
  targetId = employeeId if employeeId is not None else requireOwnEmployeeId(actor)
  employee = getEmployeeRow(conn, targetId)
  requireCanView(actor, employee)
  return [balanceFor(conn, employee["id"], employee["hired_on"], leaveType, day) for leaveType in listLeaveTypes(conn)]


# ---------- 額度調整 ----------


def createAdjustment(conn: Connection, actor: Actor, data: dict, now: datetime) -> dict:
  employee = getEmployeeRow(conn, data["employeeId"])
  leaveType = getLeaveType(conn, data["leaveTypeId"])
  if leaveType["quotaKind"] == "none":
    raise AppError("VALIDATION", "不限額度的假別不需要調整", 422, {"field": "leaveTypeId"})
  periodStart = data["periodStart"]
  period = rules.periodFor(leaveType["quotaKind"], leaveType["annualCapHours"], employee["hired_on"], periodStart)
  if period is None or period.start != periodStart:
    raise AppError("VALIDATION", "年度開始日不對：要填這位員工這個假別某個年度的第一天", 422, {"field": "periodStart"})
  hours = data["hours"]
  if not isinstance(hours, int) or hours == 0:
    raise AppError("VALIDATION", "時數不能是 0", 422, {"field": "hours"})
  reason = requireText(data.get("reason"), "原因")
  with mapDbErrors(conn):
    adjustmentId = conn.execute(
      "INSERT INTO leave_adjustments (employee_id, leave_type_id, period_start, hours, reason, created_by, created_at) "
      "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
      (employee["id"], leaveType["id"], periodStart, hours, reason, actor.userId, now),
    ).fetchone()["id"]
  adjustment = camelizeRow(conn.execute(f"{adjustmentSelect} WHERE a.id = %s", (adjustmentId,)).fetchone())
  writeAudit(conn, actor, "leave", "createLeaveAdjustment", "leaveAdjustment", adjustmentId, None, adjustment)
  return adjustment


def listAdjustments(conn: Connection, employeeId: int) -> list[dict]:
  rows = conn.execute(f"{adjustmentSelect} WHERE a.employee_id = %s ORDER BY a.period_start DESC, a.id DESC", (employeeId,)).fetchall()
  return camelizeRow(rows)


# ---------- 未休特休 ----------


def listUnused(conn: Connection, periodEndFrom: date, periodEndTo: date) -> list[dict]:
  if periodEndTo < periodEndFrom:
    raise AppError("VALIDATION", "結束日不能早於開始日", 422)
  row = conn.execute(f"SELECT {typeColumns} FROM leave_types WHERE quota_kind = 'seniority'").fetchone()
  if row is None:
    return []
  annual = camelizeRow(row)
  employees = conn.execute(
    "SELECT e.id, e.name, d.name AS department_name, e.hired_on, e.left_on "
    "FROM employees e JOIN departments d ON d.id = e.department_id ORDER BY e.employee_no"
  ).fetchall()
  result = []
  for employee in employees:
    day = rules.addMonths(employee["hired_on"], 6)
    while True:
      period = rules.seniorityPeriod(employee["hired_on"], day)
      # 離職後才開始的年度不算
      if period.end > periodEndTo or (employee["left_on"] and period.start > employee["left_on"]):
        break
      if period.end >= periodEndFrom:
        balance = balanceFor(conn, employee["id"], employee["hired_on"], annual, period.start)
        if balance["remainingHours"] > 0:
          result.append({
            "employeeId": employee["id"], "employeeName": employee["name"], "departmentName": employee["department_name"],
            "periodStart": balance["periodStart"], "periodEnd": balance["periodEnd"], "quotaHours": balance["quotaHours"],
            "adjustmentHours": balance["adjustmentHours"], "usedHours": balance["approvedHours"] + balance["pendingHours"],
            "unusedHours": balance["remainingHours"],
          })
      day = period.end + timedelta(days=1)
  return sorted(result, key=lambda item: (item["periodEnd"], item["employeeName"]))
