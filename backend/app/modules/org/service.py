from datetime import date

from psycopg import Connection

from app.infra.actor import Actor
from app.infra.db import mapDbErrors
from app.infra.errors import AppError
from app.infra.serialize import camelizeRow
from app.infra.validate import requireText
from app.modules.core.service import writeAudit

departmentColumns = "id, name, parent_id"
employeeColumns = "id, employee_no, name, email, department_id, job_title, manager_id, hired_on, is_active, left_on"
calendarKinds = {"holiday", "makeup_workday"}

# API 用的 camelCase 欄位名稱對資料表欄位
departmentFields = {"name": "name", "parentId": "parent_id"}
employeeFields = {
  "employeeNo": "employee_no",
  "name": "name",
  "email": "email",
  "departmentId": "department_id",
  "jobTitle": "job_title",
  "managerId": "manager_id",
  "hiredOn": "hired_on",
  "isActive": "is_active",
  "leftOn": "left_on",
}
requiredTextFields = {"name", "employeeNo", "jobTitle"}

# 兩個人同時改部門或主管，可能各自通過循環檢查、合起來卻形成循環；用同一把鎖讓它們排隊
hierarchyLockKey = 7301


def validateFields(fields: dict, allowed: dict) -> dict:
  unknown = set(fields) - set(allowed)
  if unknown:
    raise AppError("VALIDATION", f"不能修改的欄位：{', '.join(sorted(unknown))}", 422)
  return {key: requireText(value, key) if key in requiredTextFields else value for key, value in fields.items()}


def chainContains(conn: Connection, table: str, column: str, startId: int, targetId: int) -> bool:
  # 從 startId 沿著上層一路往上走，看會不會走到 targetId；UNION 去重，資料已經有循環時也會結束
  row = conn.execute(
    f"WITH RECURSIVE chain(id) AS (SELECT %s::int UNION SELECT t.{column} FROM {table} t JOIN chain c ON t.id = c.id "
    f"WHERE t.{column} IS NOT NULL) SELECT 1 FROM chain WHERE id = %s",
    (startId, targetId),
  ).fetchone()
  return row is not None


def fetchRow(conn: Connection, table: str, columns: str, rowId: int, label: str) -> dict:
  row = conn.execute(f"SELECT {columns} FROM {table} WHERE id = %s", (rowId,)).fetchone()
  if row is None:
    raise AppError("NOT_FOUND", f"找不到{label}", 404)
  return camelizeRow(row)


def applyUpdate(conn: Connection, table: str, columns: str, rowId: int, fields: dict, mapping: dict) -> dict:
  assignments = ", ".join(f"{mapping[key]} = %s" for key in fields)
  with mapDbErrors(conn):
    row = conn.execute(
      f"UPDATE {table} SET {assignments} WHERE id = %s RETURNING {columns}", [*fields.values(), rowId]
    ).fetchone()
  return camelizeRow(row)


def createDepartment(conn: Connection, actor: Actor, name: str, parentId: int | None = None) -> dict:
  name = requireText(name, "部門名稱")
  with mapDbErrors(conn):
    row = conn.execute(
      f"INSERT INTO departments (name, parent_id) VALUES (%s, %s) RETURNING {departmentColumns}", (name, parentId)
    ).fetchone()
  department = camelizeRow(row)
  writeAudit(conn, actor, "org", "createDepartment", "department", department["id"], None, department)
  return department


def updateDepartment(conn: Connection, actor: Actor, departmentId: int, fields: dict) -> dict:
  fields = validateFields(fields, departmentFields)
  conn.execute("SELECT pg_advisory_xact_lock(%s)", (hierarchyLockKey,))
  before = fetchRow(conn, "departments", departmentColumns, departmentId, "部門")
  if not fields:
    return before
  if fields.get("parentId") is not None and chainContains(conn, "departments", "parent_id", fields["parentId"], departmentId):
    raise AppError("DEPARTMENT_CYCLE", "部門的上層不能是自己或自己的下層部門", 422)
  after = applyUpdate(conn, "departments", departmentColumns, departmentId, fields, departmentFields)
  writeAudit(conn, actor, "org", "updateDepartment", "department", departmentId, before, after)
  return after


def listDepartments(conn: Connection) -> list[dict]:
  return camelizeRow(conn.execute(f"SELECT {departmentColumns} FROM departments ORDER BY id").fetchall())


def createEmployee(conn: Connection, actor: Actor, data: dict) -> dict:
  data = validateFields(data, employeeFields)
  for key in ("employeeNo", "name", "jobTitle"):
    requireText(data.get(key), key)
  with mapDbErrors(conn):
    row = conn.execute(
      f"INSERT INTO employees (employee_no, name, email, department_id, job_title, manager_id, hired_on) "
      f"VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING {employeeColumns}",
      (
        data["employeeNo"], data["name"], data.get("email"), data.get("departmentId"),
        data["jobTitle"], data.get("managerId"), data.get("hiredOn"),
      ),
    ).fetchone()
  employee = camelizeRow(row)
  writeAudit(conn, actor, "org", "createEmployee", "employee", employee["id"], None, employee)
  return employee


def updateEmployee(conn: Connection, actor: Actor, employeeId: int, fields: dict) -> dict:
  fields = validateFields(fields, employeeFields)
  conn.execute("SELECT pg_advisory_xact_lock(%s)", (hierarchyLockKey,))
  before = fetchRow(conn, "employees", employeeColumns, employeeId, "員工")
  if not fields:
    return before
  if fields.get("managerId") is not None and chainContains(conn, "employees", "manager_id", fields["managerId"], employeeId):
    raise AppError("MANAGER_CYCLE", "員工的主管不能是自己或自己的下屬", 422)
  after = applyUpdate(conn, "employees", employeeColumns, employeeId, fields, employeeFields)
  writeAudit(conn, actor, "org", "updateEmployee", "employee", employeeId, before, after)
  return after


def getEmployee(conn: Connection, employeeId: int) -> dict:
  return fetchRow(conn, "employees", employeeColumns, employeeId, "員工")


def listEmployees(conn: Connection, includeInactive: bool = False) -> list[dict]:
  where = "" if includeInactive else "WHERE is_active"
  return camelizeRow(conn.execute(f"SELECT {employeeColumns} FROM employees {where} ORDER BY employee_no").fetchall())


def listSubordinateIds(conn: Connection, employeeId: int) -> set[int]:
  # UNION 會去重，主管鏈有循環時遞迴也會結束
  rows = conn.execute(
    "WITH RECURSIVE sub(id) AS (SELECT id FROM employees WHERE manager_id = %s "
    "UNION SELECT e.id FROM employees e JOIN sub s ON e.manager_id = s.id) SELECT id FROM sub WHERE id <> %s",
    (employeeId, employeeId),
  ).fetchall()
  return {row["id"] for row in rows}


def upsertCalendarDay(conn: Connection, actor: Actor, day: date, kind: str, name: str) -> dict:
  if kind not in calendarKinds:
    raise AppError("VALIDATION", f"kind 只能是 {', '.join(sorted(calendarKinds))}", 422)
  name = requireText(name, "名稱")
  existing = conn.execute("SELECT day, kind, name FROM calendar_days WHERE day = %s", (day,)).fetchone()
  row = conn.execute(
    "INSERT INTO calendar_days (day, kind, name) VALUES (%s, %s, %s) "
    "ON CONFLICT (day) DO UPDATE SET kind = EXCLUDED.kind, name = EXCLUDED.name RETURNING day, kind, name",
    (day, kind, name),
  ).fetchone()
  after = camelizeRow(row)
  before = camelizeRow(existing) if existing else None
  writeAudit(conn, actor, "org", "upsertCalendarDay", "calendarDay", day.isoformat(), before, after)
  return after


def deleteCalendarDay(conn: Connection, actor: Actor, day: date) -> None:
  row = conn.execute("DELETE FROM calendar_days WHERE day = %s RETURNING day, kind, name", (day,)).fetchone()
  if row is None:
    raise AppError("NOT_FOUND", "找不到這一天的行事曆設定", 404)
  writeAudit(conn, actor, "org", "deleteCalendarDay", "calendarDay", day.isoformat(), camelizeRow(row), None)


def listCalendarDays(conn: Connection, start: date, end: date) -> list[dict]:
  rows = conn.execute(
    "SELECT day, kind, name FROM calendar_days WHERE day BETWEEN %s AND %s ORDER BY day", (start, end)
  ).fetchall()
  return camelizeRow(rows)
