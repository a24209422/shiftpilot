import re
from datetime import date, datetime, time, timedelta

from psycopg import Connection

from app.infra.actor import Actor
from app.infra.db import mapDbErrors
from app.infra.errors import AppError
from app.infra.serialize import camelizeRow
from app.infra.validate import requireText
from app.modules.core.service import writeAudit
from app.modules.shift import rules

typeColumns = "id, code, name, start_time, end_time, break_start, break_end, is_default, is_active"
timePattern = re.compile(r"^\d{2}:\d{2}$")
typeCreateFields = {"code", "name", "startTime", "endTime", "breakStart", "breakEnd", "isDefault"}
# 班是即時推算的：時間一改，過去所有用這個班的日子都會跟著變
typeImmutableFields = ("code", "startTime", "endTime", "breakStart", "breakEnd")
typeUpdateFields = {"name": "name", "isActive": "is_active", "isDefault": "is_default"}
maxScheduleDays = 31


# ---------- 班別 ----------


def formatTime(value: time | None) -> str | None:
  return value.strftime("%H:%M") if value is not None else None


def parseTime(value, field: str) -> time | None:
  if value is None:
    return None
  if not isinstance(value, str) or not timePattern.match(value):
    raise AppError("VALIDATION", "時間格式必須是 HH:MM", 422, {"field": field})
  try:
    return time.fromisoformat(value)
  except ValueError:
    raise AppError("VALIDATION", "時間不是有效的時刻", 422, {"field": field})


def serializeType(row: dict) -> dict:
  return {
    "id": row["id"], "code": row["code"], "name": row["name"],
    "startTime": formatTime(row["start_time"]), "endTime": formatTime(row["end_time"]),
    "breakStart": formatTime(row["break_start"]), "breakEnd": formatTime(row["break_end"]),
    "isDefault": row["is_default"], "isActive": row["is_active"],
  }


def toShiftType(row: dict) -> rules.ShiftType:
  return rules.ShiftType(row["id"], row["name"], row["start_time"], row["end_time"], row["break_start"], row["break_end"])


def listShiftTypes(conn: Connection, includeInactive: bool = False) -> list[dict]:
  where = "" if includeInactive else "WHERE is_active"
  return [serializeType(row) for row in conn.execute(f"SELECT {typeColumns} FROM shift_types {where} ORDER BY id").fetchall()]


def getShiftType(conn: Connection, shiftTypeId: int) -> dict:
  row = conn.execute(f"SELECT {typeColumns} FROM shift_types WHERE id = %s", (shiftTypeId,)).fetchone()
  if row is None:
    raise AppError("NOT_FOUND", "找不到班別", 404)
  return serializeType(row)


def createShiftType(conn: Connection, actor: Actor, data: dict) -> dict:
  unknown = set(data) - typeCreateFields
  if unknown:
    raise AppError("VALIDATION", f"不能設定的欄位：{', '.join(sorted(unknown))}", 422)
  code = requireText(data.get("code"), "代碼")
  name = requireText(data.get("name"), "名稱")
  startTime = parseTime(data.get("startTime"), "startTime")
  endTime = parseTime(data.get("endTime"), "endTime")
  if startTime is None or endTime is None:
    raise AppError("VALIDATION", "上班與下班時間必填", 422, {"field": "startTime" if startTime is None else "endTime"})
  breakStart = parseTime(data.get("breakStart"), "breakStart")
  breakEnd = parseTime(data.get("breakEnd"), "breakEnd")
  rules.validateShiftTimes(startTime, endTime, breakStart, breakEnd)
  isDefault = bool(data.get("isDefault"))
  with mapDbErrors(conn):
    if isDefault:
      conn.execute("UPDATE shift_types SET is_default = false WHERE is_default")
    row = conn.execute(
      f"INSERT INTO shift_types (code, name, start_time, end_time, break_start, break_end, is_default) "
      f"VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING {typeColumns}",
      (code, name, startTime, endTime, breakStart, breakEnd, isDefault),
    ).fetchone()
  shiftType = serializeType(row)
  writeAudit(conn, actor, "shift", "createShiftType", "shiftType", shiftType["id"], None, shiftType)
  return shiftType


def updateShiftType(conn: Connection, actor: Actor, shiftTypeId: int, fields: dict) -> dict:
  for frozen in typeImmutableFields:
    if frozen in fields:
      raise AppError("SHIFT_TYPE_IMMUTABLE", "班別的代碼與時間建立後不能修改，請新增一個班別", 422, {"field": frozen})
  unknown = set(fields) - set(typeUpdateFields)
  if unknown:
    raise AppError("VALIDATION", f"不能修改的欄位：{', '.join(sorted(unknown))}", 422)
  if "name" in fields:
    fields = {**fields, "name": requireText(fields["name"], "名稱")}
  before = getShiftType(conn, shiftTypeId)
  if not fields:
    return before
  willBeActive = fields.get("isActive", before["isActive"])
  willBeDefault = fields.get("isDefault", before["isDefault"])
  if willBeDefault and not willBeActive:
    if before["isDefault"] and fields.get("isActive") is False:
      raise AppError("SHIFT_DEFAULT_REQUIRED", "預設班不能停用，請先把別的班別設為預設", 409)
    raise AppError("SHIFT_TYPE_INACTIVE", "停用的班別不能設為預設", 422, {"field": "isDefault"})
  assignments = ", ".join(f"{typeUpdateFields[key]} = %s" for key in fields)
  with mapDbErrors(conn):
    if fields.get("isDefault") is True:
      conn.execute("UPDATE shift_types SET is_default = false WHERE is_default AND id <> %s", (shiftTypeId,))
    conn.execute(f"UPDATE shift_types SET {assignments} WHERE id = %s", [*fields.values(), shiftTypeId])
  after = getShiftType(conn, shiftTypeId)
  writeAudit(conn, actor, "shift", "updateShiftType", "shiftType", shiftTypeId, before, after)
  return after


# ---------- 推算 ----------


def loadShiftTypes(conn: Connection) -> tuple[dict[int, rules.ShiftType], rules.ShiftType | None]:
  rows = conn.execute(f"SELECT {typeColumns} FROM shift_types").fetchall()
  # 停用的班別也要載入：已經排好的班照舊推算
  types = {row["id"]: toShiftType(row) for row in rows}
  default = next((types[row["id"]] for row in rows if row["is_default"]), None)
  return types, default


def resolveRange(conn: Connection, employeeIds: list[int] | None, startDay: date, endDay: date) -> list[tuple[dict, list[rules.ResolvedDay]]]:
  employees = conn.execute(
    "SELECT id, employee_no, hired_on, left_on, is_active FROM employees "
    "WHERE (%(ids)s::int[] IS NULL AND is_active) OR id = ANY(%(ids)s::int[]) ORDER BY employee_no",
    {"ids": employeeIds},
  ).fetchall()
  ids = [employee["id"] for employee in employees]
  shiftTypes, defaultShift = loadShiftTypes(conn)
  rosterRows = conn.execute(
    "SELECT r.id, r.employee_id, r.effective_from, d.weekday, d.shift_type_id FROM shift_rosters r "
    "LEFT JOIN shift_roster_days d ON d.roster_id = r.id WHERE r.employee_id = ANY(%s) AND r.effective_from <= %s "
    "ORDER BY r.employee_id, r.effective_from, d.weekday",
    (ids, endDay),
  ).fetchall()
  rosterDays: dict[int, dict] = {}
  rosterMeta: dict[int, tuple[int, date]] = {}
  for row in rosterRows:
    rosterMeta[row["id"]] = (row["employee_id"], row["effective_from"])
    days = rosterDays.setdefault(row["id"], {})
    if row["weekday"] is not None:
      days[row["weekday"]] = row["shift_type_id"]
  rosters: dict[int, list[rules.Roster]] = {}
  for rosterId, (employeeId, effectiveFrom) in rosterMeta.items():
    rosters.setdefault(employeeId, []).append(rules.Roster(effectiveFrom, rosterDays[rosterId]))
  overrides = {
    (row["employee_id"], row["day"]): rules.Override(row["shift_type_id"], row["note"])
    for row in conn.execute(
      "SELECT employee_id, day, shift_type_id, note FROM shift_overrides WHERE employee_id = ANY(%s) AND day BETWEEN %s AND %s",
      (ids, startDay, endDay),
    ).fetchall()
  }
  calendar = {
    row["day"]: (row["kind"], row["name"])
    for row in conn.execute("SELECT day, kind, name FROM calendar_days WHERE day BETWEEN %s AND %s", (startDay, endDay)).fetchall()
  }
  dayCount = (endDay - startDay).days + 1
  result = []
  for employee in employees:
    dates = rules.EmployeeDates(employee["hired_on"], employee["left_on"], employee["is_active"])
    employeeRosters = sorted(rosters.get(employee["id"], []), key=lambda roster: roster.effectiveFrom)
    resolved = []
    for offset in range(dayCount):
      day = startDay + timedelta(days=offset)
      resolved.append(rules.resolveDay(
        day, dates, overrides.get((employee["id"], day)), rules.activeRoster(employeeRosters, day),
        calendar.get(day), shiftTypes, defaultShift,
      ))
    result.append((employee, resolved))
  return result


def serializeDay(employeeId: int, resolved: rules.ResolvedDay) -> dict:
  return {
    "employeeId": employeeId, "day": resolved.day, "source": resolved.source,
    "shiftTypeId": resolved.shift.id if resolved.shift else None, "shiftName": resolved.shift.name if resolved.shift else None,
    "startAt": resolved.startAt, "endAt": resolved.endAt, "breakStartAt": resolved.breakStartAt, "breakEndAt": resolved.breakEndAt,
    "holidayName": resolved.holidayName, "overrideNote": resolved.overrideNote,
  }


def getSchedule(conn: Connection, employeeIds: list[int] | None, startDay: date, endDay: date) -> list[dict]:
  if endDay < startDay or (endDay - startDay).days >= maxScheduleDays:
    raise AppError("VALIDATION", f"查詢區間要 1 到 {maxScheduleDays} 天", 422)
  rows = [serializeDay(employee["id"], day) for employee, days in resolveRange(conn, employeeIds, startDay, endDay) for day in days]
  return camelizeRow(rows)


def rangeDays(startAt: datetime, endAt: datetime) -> tuple[date, date]:
  # 前一晚的跨日班會延續到區間裡；結束在 00:00 時最後一天是前一天
  return startAt.date() - timedelta(days=1), (endAt - timedelta(microseconds=1)).date()


def workWindows(conn: Connection, employeeIds: list[int], startAt: datetime, endAt: datetime) -> dict[int, list[tuple[datetime, datetime]]]:
  result: dict[int, list[tuple[datetime, datetime]]] = {employeeId: [] for employeeId in employeeIds}
  if not employeeIds or endAt <= startAt:
    return result
  startDay, endDay = rangeDays(startAt, endAt)
  for employee, days in resolveRange(conn, employeeIds, startDay, endDay):
    windows = [window for day in days for window in rules.workWindowsOf(day)]
    result[employee["id"]] = rules.clipWindows(windows, startAt, endAt)
  return result


def shiftSpans(conn: Connection, employeeIds: list[int], startAt: datetime, endAt: datetime) -> dict[int, list[rules.ResolvedDay]]:
  if not employeeIds:
    return {}
  startDay, endDay = rangeDays(startAt, endAt)
  return {employee["id"]: days for employee, days in resolveRange(conn, employeeIds, startDay, endDay)}
