from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID

import psycopg
from psycopg import Connection

from app.infra.actor import Actor
from app.modules.leave import service as leaveService
from app.modules.shift import rules as shiftRules
from app.modules.shift import service as shiftService

windowDays = 90
maxRows = 200
statementTimeout = "5s"

# 沙盒裡的資料表；順序就是寫入時的欄位順序，也是給模型看的說明順序
sandboxTables: list[tuple[str, str]] = [
  ("departments", "id int, name text, parent_id int"),
  ("employees", "id int, employee_no text, name text, department_id int, job_title text, manager_id int, hired_on date"),
  ("resources", "id int, name text, kind text, location text, capacity int"),
  ("bookings", "id int, title text, category text, start_at timestamp, end_at timestamp"),
  ("booking_resources", "booking_id int, resource_id int"),
  ("booking_participants", "booking_id int, employee_id int, role text"),
  ("leave_requests", "id int, employee_id int, leave_type text, start_at timestamp, end_at timestamp, hours int, status text, reason text"),
  ("day_shifts", "employee_id int, day date, shift_name text, start_at timestamp, end_at timestamp, break_start_at timestamp, break_end_at timestamp, source text"),
  ("busy_periods", "employee_id int, start_at timestamp, end_at timestamp, kind text, label text"),
  ("calendar_days", "day date, kind text, name text"),
]


@dataclass
class SandboxData:
  windowStart: date
  windowEnd: date
  rows: dict[str, list[tuple]]
  vocabulary: dict[str, list[str]]
  # 助理提案要帶假別 id；放在這裡而不是沙盒資料表，模型的 SQL 看不到
  leaveTypes: list[tuple[int, str]] = field(default_factory=list)


def dataWindow(today: date) -> tuple[date, date]:
  return today - timedelta(days=windowDays), today + timedelta(days=windowDays)


def tuples(conn: Connection, sql: str, params: tuple = ()) -> list[tuple]:
  return [tuple(row.values()) for row in conn.execute(sql, params).fetchall()]


def names(conn: Connection, sql: str) -> list[str]:
  return [row["name"] for row in conn.execute(sql).fetchall()]


def visibleLeave(conn: Connection, actor: Actor, startAt: datetime, endAt: datetime) -> list[tuple]:
  rows = conn.execute(
    "SELECT r.id, r.employee_id, t.name AS leave_type, r.start_at, r.end_at, r.hours, r.status, r.reason, e.manager_id "
    "FROM leave_requests r JOIN leave_types t ON t.id = r.leave_type_id JOIN employees e ON e.id = r.employee_id "
    "WHERE r.start_at < %s AND r.end_at > %s ORDER BY r.start_at, r.id",
    (endAt, startAt),
  ).fetchall()
  isManager = leaveService.isLeaveManager(actor)
  result = []
  for row in rows:
    # 跟畫面一樣：假別與事由只有本人、直屬主管、人資看得到；其他人只知道那段時間不在
    canSee = isManager or (actor.employeeId is not None and actor.employeeId in (row["employee_id"], row["manager_id"]))
    if not canSee and row["status"] not in ("pending", "approved"):
      continue
    result.append((
      row["id"], row["employee_id"], row["leave_type"] if canSee else None, row["start_at"], row["end_at"],
      row["hours"], row["status"], row["reason"] if canSee else None,
    ))
  return result


def leaveBusy(conn: Connection, startAt: datetime, endAt: datetime) -> list[tuple]:
  leaves = conn.execute(
    "SELECT employee_id, start_at, end_at, status FROM leave_requests "
    "WHERE status IN ('pending', 'approved') AND start_at < %s AND end_at > %s ORDER BY start_at, id",
    (endAt, startAt),
  ).fetchall()
  windows = shiftService.workWindows(conn, sorted({leave["employee_id"] for leave in leaves}), startAt, endAt)
  result = []
  for leave in leaves:
    label = "請假" if leave["status"] == "approved" else "請假（待核准）"
    # 跟時間軸一樣依班裁成片段，「誰有空」才不會把下班時間也算成請假
    for segmentStart, segmentEnd in shiftRules.clipWindows(windows[leave["employee_id"]], leave["start_at"], leave["end_at"]):
      result.append((leave["employee_id"], segmentStart, segmentEnd, "leave", label))
  return result


def collectSandboxData(conn: Connection, actor: Actor, today: date) -> SandboxData:
  windowStart, windowEnd = dataWindow(today)
  startAt = datetime.combine(windowStart, time.min)
  endAt = datetime.combine(windowEnd + timedelta(days=1), time.min)
  rows: dict[str, list[tuple]] = {}
  rows["departments"] = tuples(conn, "SELECT id, name, parent_id FROM departments ORDER BY id")
  rows["employees"] = tuples(
    conn, "SELECT id, employee_no, name, department_id, job_title, manager_id, hired_on FROM employees WHERE is_active ORDER BY employee_no"
  )
  rows["resources"] = tuples(conn, "SELECT id, name, kind, location, capacity FROM resources WHERE is_active ORDER BY id")
  bookings = conn.execute(
    "SELECT id, title, category, start_at, end_at FROM bookings WHERE status = 'confirmed' AND start_at < %s AND end_at > %s ORDER BY start_at, id",
    (endAt, startAt),
  ).fetchall()
  bookingIds = [booking["id"] for booking in bookings]
  rows["bookings"] = [tuple(booking.values()) for booking in bookings]
  rows["booking_resources"] = tuples(
    conn, "SELECT booking_id, resource_id FROM booking_resources WHERE booking_id = ANY(%s) ORDER BY booking_id, resource_id", (bookingIds,)
  )
  participants = conn.execute(
    "SELECT booking_id, employee_id, role FROM booking_participants WHERE booking_id = ANY(%s) ORDER BY booking_id, employee_id",
    (bookingIds,),
  ).fetchall()
  rows["booking_participants"] = [tuple(row.values()) for row in participants]
  rows["leave_requests"] = visibleLeave(conn, actor, startAt, endAt)
  rows["day_shifts"] = [
    (employee["id"], day.day, day.shift.name if day.shift else None, day.startAt, day.endAt, day.breakStartAt, day.breakEndAt, day.source)
    for employee, days in shiftService.resolveRange(conn, None, windowStart, windowEnd)
    for day in days
  ]
  bookingById = {booking["id"]: booking for booking in bookings}
  meetingBusy = [
    (row["employee_id"], bookingById[row["booking_id"]]["start_at"], bookingById[row["booking_id"]]["end_at"], "meeting", bookingById[row["booking_id"]]["title"])
    for row in participants
  ]
  rows["busy_periods"] = meetingBusy + leaveBusy(conn, startAt, endAt)
  rows["calendar_days"] = tuples(conn, "SELECT day, kind, name FROM calendar_days WHERE day BETWEEN %s AND %s ORDER BY day", (windowStart, windowEnd))
  vocabulary = {
    "departments": [row[1] for row in rows["departments"]],
    "shifts": names(conn, "SELECT name FROM shift_types WHERE is_active ORDER BY id"),
    "leaveTypes": names(conn, "SELECT name FROM leave_types WHERE is_active ORDER BY id"),
    "resources": [row[1] for row in rows["resources"]],
  }
  leaveTypes = tuples(conn, "SELECT id, name FROM leave_types WHERE is_active ORDER BY id")
  return SandboxData(windowStart, windowEnd, rows, vocabulary, leaveTypes)


@contextmanager
def openSandbox(qaDatabaseUrl: str, data: SandboxData):
  # autocommit：每一句自成交易；切成唯讀之後，模型的 SQL 也在自己的唯讀交易裡執行
  with psycopg.connect(qaDatabaseUrl, autocommit=True) as conn:
    # 建表、複製資料、收回寫入權限放在同一個交易，省掉每句一次的 fsync
    with conn.transaction():
      for name, columns in sandboxTables:
        conn.execute(f"CREATE TEMP TABLE {name} ({columns})")
        tableRows = data.rows[name]
        if tableRows:
          with conn.cursor().copy(f"COPY {name} FROM STDIN") as copy:
            for row in tableRows:
              copy.write_row(row)
        # 唯讀交易仍允許寫暫存表；擁有者收回自己的寫入權限後，唯讀狀態下也無法再 GRANT 回來
        conn.execute(f"REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON {name} FROM CURRENT_USER")
    # 只看得到自己的暫存表；真實資料表本來就沒有權限，這裡再讓沒寫 schema 的名稱只找暫存表
    conn.execute("SET search_path = pg_temp")
    conn.execute(f"SET statement_timeout = '{statementTimeout}'")
    conn.execute("SET default_transaction_read_only = on")
    yield conn


def jsonValue(value):
  # datetime 是 date 的子類別，要先判斷
  if isinstance(value, datetime):
    return value.isoformat(timespec="seconds")
  if isinstance(value, (date, time)):
    return value.isoformat()
  if isinstance(value, Decimal):
    return float(value)
  if isinstance(value, timedelta):
    return str(value)
  if isinstance(value, UUID):
    return str(value)
  if isinstance(value, (bytes, bytearray, memoryview)):
    return bytes(value).hex()
  if isinstance(value, (list, tuple)):
    return [jsonValue(item) for item in value]
  if isinstance(value, dict):
    return {str(key): jsonValue(item) for key, item in value.items()}
  return value


def runQuery(conn: Connection, sql: str, params: dict | None = None) -> tuple[list[str], list[list], bool]:
  # 注意：pg_cancel_backend、pg_terminate_backend、pg_advisory_lock 這類函式無法用權限擋下（同一個角色的連線本來就能互相操作），
  # 只能靠 sqlguard 在送進來之前禁止；這裡的防線只負責「就算 SQL 檢查被繞過，沙盒本身仍然唯讀、有逾時」。
  # force_rollback：交易結束一定回滾，模型用 set_config(..., false) 改的連線設定（唯讀、逾時）都會還原。
  # 具名游標只能執行會回傳資料列的陳述式，其他一律丟 psycopg.Error，呼叫端必須接住。
  # 具名游標在資料庫端分批取：交叉連接不會把上百萬列送到應用程式。
  with conn.transaction(force_rollback=True):
    with conn.cursor(name="qaQuery") as cursor:
      cursor.execute(sql, params)
      columns = [column.name for column in cursor.description]
      fetched = cursor.fetchmany(maxRows + 1)
  return columns, [[jsonValue(value) for value in row] for row in fetched[:maxRows]], len(fetched) > maxRows
