import re
from datetime import date, datetime, time, timedelta

from psycopg import Connection

from app.infra.actor import Actor
from app.infra.db import mapDbErrors
from app.infra.errors import AppError
from app.infra.permissions import hasPermission
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


# ---------- 誰可以排班 ----------


def requireCanSchedule(conn: Connection, actor: Actor, employeeId: int) -> dict:
  employee = conn.execute("SELECT id, name, manager_id, hired_on FROM employees WHERE id = %s", (employeeId,)).fetchone()
  if employee is None:
    raise AppError("NOT_FOUND", "找不到員工", 404)
  if hasPermission(actor.role, "shift.manage"):
    return employee
  # 主管只能排直屬下屬；主管自己的班由人資排
  if actor.employeeId is not None and employee["manager_id"] == actor.employeeId:
    return employee
  raise AppError("FORBIDDEN", "只有人資或直屬主管可以排這位員工的班", 403)


def requirePastAllowed(actor: Actor, day: date, today: date) -> None:
  # 過去的班會影響已核准請假的對照；更正歷史只交給人資
  if day < today and not hasPermission(actor.role, "shift.manage"):
    raise AppError("SHIFT_PAST_DAY", "只有人資可以排今天以前的班", 403)


def requireActiveType(conn: Connection, shiftTypeId, field: str) -> None:
  row = conn.execute("SELECT is_active FROM shift_types WHERE id = %s", (shiftTypeId,)).fetchone()
  if row is None:
    raise AppError("VALIDATION", "找不到班別", 422, {"field": field})
  if not row["is_active"]:
    raise AppError("SHIFT_TYPE_INACTIVE", "這個班別已經停用，不能再排", 422, {"field": field})


# ---------- 週班表 ----------


def loadRosters(conn: Connection, where: str, params: tuple) -> list[dict]:
  rows = conn.execute(
    "SELECT r.id, r.employee_id, r.effective_from, r.created_by, r.created_at, d.weekday, d.shift_type_id, t.name AS shift_name "
    "FROM shift_rosters r LEFT JOIN shift_roster_days d ON d.roster_id = r.id LEFT JOIN shift_types t ON t.id = d.shift_type_id "
    f"WHERE {where} ORDER BY r.effective_from DESC, r.id DESC, d.weekday",
    params,
  ).fetchall()
  rosters: dict[int, dict] = {}
  for row in rows:
    roster = rosters.setdefault(row["id"], {
      "id": row["id"], "employeeId": row["employee_id"], "effectiveFrom": row["effective_from"],
      "days": [], "createdBy": row["created_by"], "createdAt": row["created_at"],
    })
    if row["weekday"] is not None:
      roster["days"].append({"weekday": row["weekday"], "shiftTypeId": row["shift_type_id"], "shiftName": row["shift_name"]})
  return camelizeRow(list(rosters.values()))


def loadRoster(conn: Connection, rosterId: int) -> dict:
  found = loadRosters(conn, "r.id = %s", (rosterId,))
  if not found:
    raise AppError("NOT_FOUND", "找不到週班表", 404)
  return found[0]


def listRosters(conn: Connection, employeeId: int) -> list[dict]:
  return loadRosters(conn, "r.employee_id = %s", (employeeId,))


def createRoster(conn: Connection, actor: Actor, data: dict, now: datetime) -> dict:
  employee = requireCanSchedule(conn, actor, data["employeeId"])
  effectiveFrom = data["effectiveFrom"]
  requirePastAllowed(actor, effectiveFrom, now.date())
  if effectiveFrom < employee["hired_on"]:
    raise AppError("ROSTER_BEFORE_HIRE", "生效日不能早於到職日", 422, {"field": "effectiveFrom"})
  days = data.get("days") or []
  weekdays = [item["weekday"] for item in days]
  if len(set(weekdays)) != len(weekdays) or any(not isinstance(weekday, int) or not 0 <= weekday <= 6 for weekday in weekdays):
    raise AppError("VALIDATION", "星期幾要是 0 到 6，而且不能重複", 422, {"field": "days"})
  for item in days:
    requireActiveType(conn, item["shiftTypeId"], "days")
  with mapDbErrors(conn):
    rosterId = conn.execute(
      "INSERT INTO shift_rosters (employee_id, effective_from, created_by, created_at) VALUES (%s, %s, %s, %s) RETURNING id",
      (employee["id"], effectiveFrom, actor.userId, now),
    ).fetchone()["id"]
    for item in sorted(days, key=lambda entry: entry["weekday"]):
      conn.execute(
        "INSERT INTO shift_roster_days (roster_id, weekday, shift_type_id) VALUES (%s, %s, %s)",
        (rosterId, item["weekday"], item["shiftTypeId"]),
      )
  roster = loadRoster(conn, rosterId)
  writeAudit(conn, actor, "shift", "createShiftRoster", "shiftRoster", rosterId, None, roster)
  return roster


def deleteRoster(conn: Connection, actor: Actor, rosterId: int, today: date) -> None:
  before = loadRoster(conn, rosterId)
  requireCanSchedule(conn, actor, before["employeeId"])
  # 已生效的班表是歷史紀錄，刪掉會讓過去的班查不回來
  if date.fromisoformat(before["effectiveFrom"]) <= today:
    raise AppError("ROSTER_ALREADY_EFFECTIVE", "已經生效的週班表不能刪除，請新增一張新的", 409)
  conn.execute("DELETE FROM shift_rosters WHERE id = %s", (rosterId,))
  writeAudit(conn, actor, "shift", "deleteShiftRoster", "shiftRoster", rosterId, before, None)


# ---------- 單日調整 ----------

overrideSelect = (
  "SELECT o.id, o.employee_id, o.day, o.shift_type_id, t.name AS shift_name, o.note, o.created_by, o.created_at, "
  "o.updated_by, o.updated_at FROM shift_overrides o LEFT JOIN shift_types t ON t.id = o.shift_type_id"
)


def findOverride(conn: Connection, employeeId: int, day: date) -> dict | None:
  row = conn.execute(f"{overrideSelect} WHERE o.employee_id = %s AND o.day = %s", (employeeId, day)).fetchone()
  return camelizeRow(row) if row else None


def listOverrides(conn: Connection, employeeId: int, startDay: date, endDay: date) -> list[dict]:
  rows = conn.execute(
    f"{overrideSelect} WHERE o.employee_id = %s AND o.day BETWEEN %s AND %s ORDER BY o.day", (employeeId, startDay, endDay)
  ).fetchall()
  return camelizeRow(rows)


def upsertOverride(conn: Connection, actor: Actor, data: dict, now: datetime) -> dict:
  employee = requireCanSchedule(conn, actor, data["employeeId"])
  requirePastAllowed(actor, data["day"], now.date())
  shiftTypeId = data.get("shiftTypeId")
  if shiftTypeId is not None:
    requireActiveType(conn, shiftTypeId, "shiftTypeId")
  note = (data.get("note") or "").strip()
  before = findOverride(conn, employee["id"], data["day"])
  with mapDbErrors(conn):
    overrideId = conn.execute(
      "INSERT INTO shift_overrides (employee_id, day, shift_type_id, note, created_by, created_at, updated_by, updated_at) "
      "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (employee_id, day) DO UPDATE SET "
      "shift_type_id = EXCLUDED.shift_type_id, note = EXCLUDED.note, updated_by = EXCLUDED.updated_by, updated_at = EXCLUDED.updated_at "
      "RETURNING id",
      (employee["id"], data["day"], shiftTypeId, note, actor.userId, now, actor.userId, now),
    ).fetchone()["id"]
  after = findOverride(conn, employee["id"], data["day"])
  writeAudit(conn, actor, "shift", "upsertShiftOverride", "shiftOverride", overrideId, before, after)
  return after


def deleteOverride(conn: Connection, actor: Actor, employeeId: int, day: date, today: date) -> None:
  requireCanSchedule(conn, actor, employeeId)
  requirePastAllowed(actor, day, today)
  before = findOverride(conn, employeeId, day)
  if before is None:
    raise AppError("NOT_FOUND", "這一天沒有單日調整", 404)
  conn.execute("DELETE FROM shift_overrides WHERE id = %s", (before["id"],))
  writeAudit(conn, actor, "shift", "deleteShiftOverride", "shiftOverride", before["id"], before, None)


# ---------- 給資源預約 ----------


def findUnavailability(conn: Connection, employeeIds: list[int], startAt: datetime, endAt: datetime) -> list[dict]:
  result = []
  for employeeId, days in shiftSpans(conn, employeeIds, startAt, endAt).items():
    # 用整個班的起訖、不扣休息：午餐時段開會很常見，不該因此跳警告
    spans = [(day.startAt, day.endAt) for day in days if day.startAt is not None and day.endAt is not None]
    if rules.isCovered(startAt, endAt, spans):
      continue
    startDay = next((day for day in days if day.day == startAt.date()), None)
    if startDay is None or startDay.startAt is None or startDay.endAt is None:
      reason = "休息日"
    else:
      reason = f"不在班（{startDay.startAt:%H:%M}–{startDay.endAt:%H:%M}）"
    # selfExempt：送出的人自己知道自己的班，資源預約不會拿這筆提醒他本人
    result.append({"employeeId": employeeId, "reason": reason, "selfExempt": True})
  return result
