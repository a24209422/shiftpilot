from dataclasses import dataclass
from datetime import datetime, time, timedelta

import psycopg
from psycopg import Connection

from app.infra.actor import Actor
from app.infra.db import mapDbErrors, savepoint
from app.infra.errors import AppError
from app.infra.permissions import hasPermission
from app.infra.registry import collectUnavailability
from app.infra.serialize import camelizeRow
from app.infra.validate import requireText
from app.modules.core.service import writeAudit

resourceColumns = "id, name, kind, location, capacity, features, is_active, note"
bookingColumns = "id, title, category, start_at, end_at, status, note, created_by, created_at"
resourceKinds = {"room", "equipment", "vehicle"}
resourceFields = {
  "name": "name", "kind": "kind", "location": "location", "capacity": "capacity",
  "features": "features", "isActive": "is_active", "note": "note",
}
bookingFieldNames = {
  "title", "category", "startAt", "endAt", "resourceIds", "participantEmployeeIds",
  "organizerEmployeeId", "note", "acknowledgeWarnings",
}


@dataclass
class BookingInput:
  title: str
  category: str
  startAt: datetime
  endAt: datetime
  resourceIds: list[int]
  participantEmployeeIds: list[int]
  organizerEmployeeId: int | None = None
  note: str | None = None
  acknowledgeWarnings: bool = False


# ---------- 資源 ----------


def checkResourceFields(fields: dict) -> None:
  unknown = set(fields) - set(resourceFields)
  if unknown:
    raise AppError("VALIDATION", f"不能設定的欄位：{', '.join(sorted(unknown))}", 422)
  if "kind" in fields and fields["kind"] not in resourceKinds:
    raise AppError("VALIDATION", f"kind 只能是 {', '.join(sorted(resourceKinds))}", 422, {"field": "kind"})
  if "features" in fields and not (isinstance(fields["features"], list) and all(isinstance(item, str) for item in fields["features"])):
    raise AppError("VALIDATION", "features 必須是文字清單", 422, {"field": "features"})


def getResource(conn: Connection, resourceId: int) -> dict:
  row = conn.execute(f"SELECT {resourceColumns} FROM resources WHERE id = %s", (resourceId,)).fetchone()
  if row is None:
    raise AppError("NOT_FOUND", "找不到資源", 404)
  return camelizeRow(row)


def createResource(conn: Connection, actor: Actor, data: dict) -> dict:
  checkResourceFields(data)
  name = requireText(data.get("name"), "資源名稱")
  if "kind" not in data:
    raise AppError("VALIDATION", "kind 必填", 422, {"field": "kind"})
  with mapDbErrors(conn):
    row = conn.execute(
      f"INSERT INTO resources (name, kind, location, capacity, features, note) VALUES (%s, %s, %s, %s, %s, %s) "
      f"RETURNING {resourceColumns}",
      (name, data["kind"], data.get("location"), data.get("capacity"), data.get("features", []), data.get("note")),
    ).fetchone()
  resource = camelizeRow(row)
  writeAudit(conn, actor, "booking", "createResource", "resource", resource["id"], None, resource)
  return resource


def updateResource(conn: Connection, actor: Actor, resourceId: int, fields: dict) -> dict:
  checkResourceFields(fields)
  if "name" in fields:
    fields = {**fields, "name": requireText(fields["name"], "資源名稱")}
  before = getResource(conn, resourceId)
  if not fields:
    return before
  assignments = ", ".join(f"{resourceFields[key]} = %s" for key in fields)
  with mapDbErrors(conn):
    row = conn.execute(
      f"UPDATE resources SET {assignments} WHERE id = %s RETURNING {resourceColumns}", [*fields.values(), resourceId]
    ).fetchone()
  after = camelizeRow(row)
  writeAudit(conn, actor, "booking", "updateResource", "resource", resourceId, before, after)
  return after


def listResources(conn: Connection, includeInactive: bool = False) -> list[dict]:
  where = "" if includeInactive else "WHERE is_active"
  return camelizeRow(conn.execute(f"SELECT {resourceColumns} FROM resources {where} ORDER BY id").fetchall())


# ---------- 讀取排程 ----------


def loadBookings(conn: Connection, bookingIds: list[int]) -> list[dict]:
  if not bookingIds:
    return []
  byId = {}
  for row in conn.execute(f"SELECT {bookingColumns} FROM bookings WHERE id = ANY(%s)", (bookingIds,)).fetchall():
    byId[row["id"]] = {**camelizeRow(row), "resources": [], "participants": []}
  for row in conn.execute(
    "SELECT br.booking_id, r.id, r.name, r.kind FROM booking_resources br JOIN resources r ON r.id = br.resource_id "
    "WHERE br.booking_id = ANY(%s) ORDER BY r.id",
    (bookingIds,),
  ).fetchall():
    byId[row["booking_id"]]["resources"].append({"id": row["id"], "name": row["name"], "kind": row["kind"]})
  for row in conn.execute(
    "SELECT p.booking_id, p.employee_id, e.name, p.role FROM booking_participants p JOIN employees e ON e.id = p.employee_id "
    "WHERE p.booking_id = ANY(%s) ORDER BY (p.role = 'organizer') DESC, p.employee_id",
    (bookingIds,),
  ).fetchall():
    byId[row["booking_id"]]["participants"].append(
      {"employeeId": row["employee_id"], "name": row["name"], "role": row["role"]}
    )
  return [byId[bookingId] for bookingId in bookingIds if bookingId in byId]


def getBooking(conn: Connection, bookingId: int) -> dict:
  found = loadBookings(conn, [bookingId])
  if not found:
    raise AppError("NOT_FOUND", "找不到排程", 404)
  return found[0]


def listBookings(
  conn: Connection,
  rangeStart: datetime,
  rangeEnd: datetime,
  resourceId: int | None = None,
  employeeId: int | None = None,
  includeCancelled: bool = False,
) -> list[dict]:
  rows = conn.execute(
    "SELECT b.id FROM bookings b WHERE b.start_at < %(rangeEnd)s AND b.end_at > %(rangeStart)s "
    "AND (%(includeCancelled)s OR b.status = 'confirmed') "
    "AND (%(resourceId)s::int IS NULL OR EXISTS (SELECT 1 FROM booking_resources br WHERE br.booking_id = b.id AND br.resource_id = %(resourceId)s)) "
    "AND (%(employeeId)s::int IS NULL OR EXISTS (SELECT 1 FROM booking_participants p WHERE p.booking_id = b.id AND p.employee_id = %(employeeId)s)) "
    "ORDER BY b.start_at, b.id",
    {
      "rangeStart": rangeStart, "rangeEnd": rangeEnd, "includeCancelled": includeCancelled,
      "resourceId": resourceId, "employeeId": employeeId,
    },
  ).fetchall()
  return loadBookings(conn, [row["id"] for row in rows])


def getSummary(conn: Connection, now: datetime) -> dict:
  dayStart = datetime.combine(now.date(), time.min)
  todayBookings = listBookings(conn, dayStart, dayStart + timedelta(days=1))
  nextRow = conn.execute(
    "SELECT id FROM bookings WHERE status = 'confirmed' AND start_at > %s ORDER BY start_at, id LIMIT 1", (now,)
  ).fetchone()
  nextBooking = getBooking(conn, nextRow["id"]) if nextRow else None
  resources = conn.execute("SELECT id, name, kind FROM resources WHERE is_active ORDER BY id").fetchall()
  currentByResource = {
    row["resource_id"]: row["booking_id"]
    for row in conn.execute(
      "SELECT resource_id, booking_id FROM booking_resources WHERE is_active AND during @> %s::timestamp", (now,)
    ).fetchall()
  }
  currentBookings = {item["id"]: item for item in loadBookings(conn, list(set(currentByResource.values())))}
  resourceStatus = [
    {
      "resourceId": resource["id"], "name": resource["name"], "kind": resource["kind"],
      "currentBooking": currentBookings.get(currentByResource.get(resource["id"])),
    }
    for resource in resources
  ]
  # 「還沒結束」的排程數：歷史排程只會越積越多，當作首頁的數字沒有意義
  bookingCount = conn.execute(
    "SELECT count(*) AS n FROM bookings WHERE status = 'confirmed' AND end_at > %s", (now,)
  ).fetchone()["n"]
  return {
    "todayBookings": todayBookings,
    "nextBooking": nextBooking,
    "resourceStatus": resourceStatus,
    "bookingCount": bookingCount,
    "resourceCount": len(resources),
  }


# ---------- 檢查 ----------


def dedupe(ids, label: str) -> list:
  # PATCH 可以帶 null：沒擋下來會在這裡變成 TypeError（500），要明確回 422
  if not isinstance(ids, list) or not all(isinstance(item, int) and not isinstance(item, bool) for item in ids):
    raise AppError("VALIDATION", f"{label} 必須是整數清單", 422, {"field": label})
  return list(dict.fromkeys(ids))


def checkTimes(startAt, endAt) -> None:
  if not isinstance(startAt, datetime) or not isinstance(endAt, datetime):
    raise AppError("VALIDATION", "開始與結束時間必填", 422)
  if endAt <= startAt:
    raise AppError("VALIDATION", "結束時間必須晚於開始時間", 422, {"field": "endAt"})


def checkReferences(conn: Connection, table: str, label: str, ids: list[int]) -> None:
  if not ids:
    return
  found = {row["id"]: row["is_active"] for row in conn.execute(f"SELECT id, is_active FROM {table} WHERE id = ANY(%s)", (ids,)).fetchall()}
  missing = [item for item in ids if item not in found]
  if missing:
    raise AppError("VALIDATION", f"找不到{label}：{missing}", 422, {"ids": missing})
  inactive = [item for item in ids if not found[item]]
  if inactive:
    raise AppError("INACTIVE_REFERENCE", f"{label}已停用：{inactive}", 422, {"ids": inactive})


def lockResources(conn: Connection, resourceIds: list[int]) -> None:
  # 排除限制本身擋得住重複預約，但兩個交易同時寫同一個資源時，其中一個會得到 DeadlockDetected 而不是乾淨的撞期錯誤。
  # 先照 id 由小到大鎖住資源列：後到的請求等前一個 commit 後，再做衝突檢查，就能看到對方並回報跟誰撞
  if resourceIds:
    conn.execute("SELECT id FROM resources WHERE id = ANY(%s) ORDER BY id FOR NO KEY UPDATE", (resourceIds,)).fetchall()


def findResourceConflicts(
  conn: Connection, resourceIds: list[int], startAt: datetime, endAt: datetime, excludeBookingId: int | None = None
) -> list[dict]:
  if not resourceIds:
    return []
  rows = conn.execute(
    "SELECT b.id AS booking_id, b.title, b.start_at, b.end_at, r.id AS resource_id, r.name AS resource_name "
    "FROM booking_resources br JOIN bookings b ON b.id = br.booking_id JOIN resources r ON r.id = br.resource_id "
    "WHERE br.resource_id = ANY(%s) AND br.is_active AND br.during && tsrange(%s, %s, '[)') "
    "AND (%s::int IS NULL OR br.booking_id <> %s) ORDER BY b.start_at, b.id",
    (resourceIds, startAt, endAt, excludeBookingId, excludeBookingId),
  ).fetchall()
  return camelizeRow(rows)


def findParticipantConflicts(
  conn: Connection, employeeIds: list[int], startAt: datetime, endAt: datetime, excludeBookingId: int | None = None
) -> list[dict]:
  if not employeeIds:
    return []
  rows = conn.execute(
    "SELECT p.employee_id, e.name, b.id AS booking_id, b.title, b.start_at, b.end_at "
    "FROM booking_participants p JOIN bookings b ON b.id = p.booking_id JOIN employees e ON e.id = p.employee_id "
    "WHERE p.employee_id = ANY(%s) AND b.status = 'confirmed' AND b.start_at < %s AND b.end_at > %s "
    "AND (%s::int IS NULL OR b.id <> %s) ORDER BY b.start_at, b.id, p.employee_id",
    (employeeIds, endAt, startAt, excludeBookingId, excludeBookingId),
  ).fetchall()
  conflicts = [{**row, "reason": "同時段已有其他排程"} for row in rows]
  names = {row["id"]: row["name"] for row in conn.execute("SELECT id, name FROM employees WHERE id = ANY(%s)", (employeeIds,)).fetchall()}
  for item in collectUnavailability(conn, employeeIds, startAt, endAt):
    # 提供者不一定帶姓名，由這裡補上
    conflicts.append({"name": names.get(item["employeeId"]), **item})
  return camelizeRow(conflicts)


def checkConflicts(
  conn: Connection,
  resourceIds: list[int],
  employeeIds: list[int],
  startAt: datetime,
  endAt: datetime,
  excludeBookingId: int | None,
  acknowledgeWarnings: bool,
) -> None:
  # 資源撞期優先：它是硬性禁止，不能用「仍要排」略過
  conflicts = findResourceConflicts(conn, resourceIds, startAt, endAt, excludeBookingId)
  if conflicts:
    raise resourceConflictError(conflicts)
  if not acknowledgeWarnings:
    warnings = findParticipantConflicts(conn, employeeIds, startAt, endAt, excludeBookingId)
    if warnings:
      raise AppError("PARTICIPANT_CONFLICT", "有參加者在這個時段不方便", 409, {"conflicts": warnings})


def resourceConflictError(conflicts: list[dict]) -> AppError:
  return AppError("RESOURCE_CONFLICT", "資源在這個時段已被預約", 409, {"conflicts": conflicts})


def canModify(actor: Actor, createdBy: int) -> bool:
  return actor.userId == createdBy or hasPermission(actor.role, "booking.writeAny")


# ---------- 寫入 ----------


def insertResources(conn: Connection, bookingId: int, resourceIds: list[int]) -> None:
  # 固定由小到大寫入：兩個請求各自搶多個資源時，順序一致才不會互相等待而死結
  for resourceId in sorted(resourceIds):
    conn.execute("INSERT INTO booking_resources (booking_id, resource_id) VALUES (%s, %s)", (bookingId, resourceId))


def insertParticipants(conn: Connection, bookingId: int, organizerId: int, attendeeIds: list[int]) -> None:
  conn.execute(
    "INSERT INTO booking_participants (booking_id, employee_id, role) VALUES (%s, %s, 'organizer')", (bookingId, organizerId)
  )
  for employeeId in attendeeIds:
    conn.execute(
      "INSERT INTO booking_participants (booking_id, employee_id, role) VALUES (%s, %s, 'attendee')", (bookingId, employeeId)
    )


def createBooking(conn: Connection, actor: Actor, data: BookingInput) -> dict:
  title = requireText(data.title, "標題")
  category = requireText(data.category, "類別")
  checkTimes(data.startAt, data.endAt)
  organizerId = data.organizerEmployeeId or actor.employeeId
  if organizerId is None:
    raise AppError("ORGANIZER_REQUIRED", "這個帳號沒有對應的員工，請指定主辦人", 422, {"field": "organizerEmployeeId"})
  resourceIds = dedupe(data.resourceIds, "resourceIds")
  attendeeIds = [item for item in dedupe(data.participantEmployeeIds, "participantEmployeeIds") if item != organizerId]
  participantIds = [organizerId, *attendeeIds]
  checkReferences(conn, "resources", "資源", resourceIds)
  checkReferences(conn, "employees", "員工", participantIds)
  lockResources(conn, resourceIds)
  checkConflicts(conn, resourceIds, participantIds, data.startAt, data.endAt, None, data.acknowledgeWarnings)
  try:
    with savepoint(conn):
      bookingId = conn.execute(
        "INSERT INTO bookings (title, category, start_at, end_at, note, created_by, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (title, category, data.startAt, data.endAt, data.note, actor.userId, datetime.now()),
      ).fetchone()["id"]
      insertResources(conn, bookingId, resourceIds)
      insertParticipants(conn, bookingId, organizerId, attendeeIds)
  except psycopg.errors.ExclusionViolation:
    # 兩個請求同時通過上面的檢查時，由資料庫的排除限制擋下後到的；回復後再查一次，才能告訴使用者跟誰撞
    raise resourceConflictError(findResourceConflicts(conn, resourceIds, data.startAt, data.endAt))
  booking = getBooking(conn, bookingId)
  writeAudit(conn, actor, "booking", "createBooking", "booking", bookingId, None, booking)
  return booking


def lockBooking(conn: Connection, bookingId: int) -> dict:
  row = conn.execute(
    "SELECT title, category, start_at, end_at, status, note, created_by FROM bookings WHERE id = %s FOR UPDATE", (bookingId,)
  ).fetchone()
  if row is None:
    raise AppError("NOT_FOUND", "找不到排程", 404)
  return row


def updateBooking(conn: Connection, actor: Actor, bookingId: int, fields: dict) -> dict:
  unknown = set(fields) - bookingFieldNames
  if unknown:
    raise AppError("VALIDATION", f"不能修改的欄位：{', '.join(sorted(unknown))}", 422)
  current = lockBooking(conn, bookingId)
  if not canModify(actor, current["created_by"]):
    raise AppError("FORBIDDEN", "只有建立者或有權限的人可以修改這筆排程", 403)
  if current["status"] == "cancelled":
    raise AppError("BOOKING_CANCELLED", "已取消的排程不能修改", 409)
  before = getBooking(conn, bookingId)
  oldResourceIds = [item["id"] for item in before["resources"]]
  oldOrganizerId = next(item["employeeId"] for item in before["participants"] if item["role"] == "organizer")
  oldAttendeeIds = [item["employeeId"] for item in before["participants"] if item["role"] == "attendee"]

  title = requireText(fields["title"], "標題") if "title" in fields else current["title"]
  category = requireText(fields["category"], "類別") if "category" in fields else current["category"]
  startAt = fields.get("startAt", current["start_at"])
  endAt = fields.get("endAt", current["end_at"])
  note = fields["note"] if "note" in fields else current["note"]
  checkTimes(startAt, endAt)
  resourceIds = dedupe(fields["resourceIds"], "resourceIds") if "resourceIds" in fields else oldResourceIds
  organizerId = fields.get("organizerEmployeeId") or oldOrganizerId
  if "participantEmployeeIds" in fields:
    attendeeIds = [item for item in dedupe(fields["participantEmployeeIds"], "participantEmployeeIds") if item != organizerId]
  else:
    # 沒有重新指定參加者時，原本的主辦人換人後仍留在名單裡
    attendeeIds = [item for item in dedupe([*oldAttendeeIds, oldOrganizerId], "participantEmployeeIds") if item != organizerId]
  participantIds = [organizerId, *attendeeIds]
  oldParticipantIds = [oldOrganizerId, *oldAttendeeIds]

  timeChanged = (startAt, endAt) != (current["start_at"], current["end_at"])
  resourcesChanged = set(resourceIds) != set(oldResourceIds)
  participantsChanged = organizerId != oldOrganizerId or set(attendeeIds) != set(oldAttendeeIds)
  if not (timeChanged or resourcesChanged or participantsChanged or (title, category, note) != (current["title"], current["category"], current["note"])):
    return before

  # 只檢查這次有變動的部分：沒動時間時，舊有的（已確認過的）參加者與資源不重新警告，也不因為資源後來被停用而擋住修改
  addedResourceIds = [item for item in resourceIds if item not in oldResourceIds]
  addedEmployeeIds = [item for item in participantIds if item not in oldParticipantIds]
  checkReferences(conn, "resources", "資源", addedResourceIds)
  checkReferences(conn, "employees", "員工", addedEmployeeIds)
  lockResources(conn, resourceIds)
  checkConflicts(
    conn,
    resourceIds if timeChanged else addedResourceIds,
    participantIds if timeChanged else addedEmployeeIds,
    startAt, endAt, bookingId, bool(fields.get("acknowledgeWarnings")),
  )
  try:
    with savepoint(conn):
      # 先拿掉不要的資源：否則改時間時，trigger 會連它也一起同步，被它的撞期擋下
      removedResourceIds = [item for item in oldResourceIds if item not in resourceIds]
      if removedResourceIds:
        conn.execute("DELETE FROM booking_resources WHERE booking_id = %s AND resource_id = ANY(%s)", (bookingId, removedResourceIds))
      conn.execute(
        "UPDATE bookings SET title = %s, category = %s, start_at = %s, end_at = %s, note = %s WHERE id = %s",
        (title, category, startAt, endAt, note, bookingId),
      )
      insertResources(conn, bookingId, addedResourceIds)
      if participantsChanged:
        conn.execute("DELETE FROM booking_participants WHERE booking_id = %s", (bookingId,))
        insertParticipants(conn, bookingId, organizerId, attendeeIds)
  except psycopg.errors.ExclusionViolation:
    raise resourceConflictError(findResourceConflicts(conn, resourceIds, startAt, endAt, bookingId))
  after = getBooking(conn, bookingId)
  writeAudit(conn, actor, "booking", "updateBooking", "booking", bookingId, before, after)
  return after


def cancelBooking(conn: Connection, actor: Actor, bookingId: int) -> dict:
  current = lockBooking(conn, bookingId)
  if not canModify(actor, current["created_by"]):
    raise AppError("FORBIDDEN", "只有建立者或有權限的人可以取消這筆排程", 403)
  if current["status"] == "cancelled":
    raise AppError("ALREADY_CANCELLED", "這筆排程已經取消", 409)
  before = getBooking(conn, bookingId)
  # trigger 會把 booking_resources.is_active 一起改成 false，資源就空出來了
  conn.execute("UPDATE bookings SET status = 'cancelled' WHERE id = %s", (bookingId,))
  after = getBooking(conn, bookingId)
  writeAudit(conn, actor, "booking", "cancelBooking", "booking", bookingId, before, after)
  return after
