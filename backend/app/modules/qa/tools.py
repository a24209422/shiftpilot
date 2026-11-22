import json
from dataclasses import dataclass
from datetime import datetime

import psycopg
from psycopg import Connection

from app.modules.qa import sandbox, sqlguard

# 小模型的 context 只有 8192 tokens，工具結果只給前幾列，加上總筆數讓它知道還有多少
modelRowLimit = 20

timeProperties = {
  "start": {"type": "string", "description": "開始時間，格式 YYYY-MM-DD HH:MM"},
  "end": {"type": "string", "description": "結束時間，格式 YYYY-MM-DD HH:MM"},
}

toolDefinitions = [
  {"type": "function", "function": {
    "name": "run_sql",
    "description": "執行一句 PostgreSQL 的 SELECT 查詢，只能用 system 說明裡的資料表。其他工具不適用時才用這個。",
    "parameters": {"type": "object", "properties": {"sql": {"type": "string", "description": "一句 SELECT 或 WITH ... SELECT"}}, "required": ["sql"]},
  }},
  {"type": "function", "function": {
    "name": "find_available_people",
    "description": "找出某段時間有空的人：當天的班蓋住整段時間，而且沒有會議或請假。問「誰有空」時用這個。",
    "parameters": {"type": "object", "properties": {
      **timeProperties, "department": {"type": "string", "description": "部門名稱，可省略；只講部分名稱也可以"},
    }, "required": ["start", "end"]},
  }},
  {"type": "function", "function": {
    "name": "get_busy_periods",
    "description": "查某段時間的會議與請假。可指定某個人或某個資源（會議室、設備、公務車），兩者擇一；都不指定時列出所有人。",
    "parameters": {"type": "object", "properties": {
      **timeProperties,
      "employee": {"type": "string", "description": "員工姓名，可省略"},
      "resource": {"type": "string", "description": "資源名稱，例如 A 會議室，可省略"},
    }, "required": ["start", "end"]},
  }},
]

availableSql = """
SELECT DISTINCT e.name, d.name AS department, e.employee_no
FROM employees e
LEFT JOIN departments d ON d.id = e.department_id
JOIN day_shifts s ON s.employee_id = e.id
WHERE s.start_at <= %(start)s AND s.end_at >= %(end)s
  AND (%(department)s::text IS NULL OR d.name LIKE '%%' || %(department)s || '%%')
  AND NOT EXISTS (SELECT 1 FROM busy_periods b WHERE b.employee_id = e.id
    AND b.start_at < %(end)s AND b.end_at > %(start)s)
ORDER BY e.employee_no
"""

resourceBusySql = """
SELECT r.name AS who, b.start_at, b.end_at, 'meeting' AS kind, b.title AS label
FROM bookings b
JOIN booking_resources br ON br.booking_id = b.id
JOIN resources r ON r.id = br.resource_id
WHERE r.name LIKE '%%' || %(resource)s || '%%' AND b.start_at < %(end)s AND b.end_at > %(start)s
ORDER BY b.start_at, r.name
"""

employeeBusySql = """
SELECT e.name AS who, b.start_at, b.end_at, b.kind, b.label
FROM busy_periods b
JOIN employees e ON e.id = b.employee_id
WHERE (%(employee)s::text IS NULL OR e.name LIKE '%%' || %(employee)s || '%%')
  AND b.start_at < %(end)s AND b.end_at > %(start)s
ORDER BY b.start_at, e.name
"""


@dataclass
class ToolResult:
  ok: bool
  columns: list[str]
  rows: list[list]
  truncated: bool
  sql: str | None
  error: str | None
  # 助理模式的提議工具回傳這個；放最後並給預設值，才不影響既有的位置參數呼叫
  proposal: dict | None = None


class ToolArgumentError(ValueError):
  pass


def describeSqlError(error: Exception) -> str:
  if isinstance(error, psycopg.errors.QueryCanceled):
    return "查詢太久（超過 5 秒）"
  # PostgreSQL 的錯誤第二行之後是 LINE／HINT 這類細節，給模型看第一行就夠它修正
  return str(error).strip().split("\n")[0]


def failed(error: str, sql: str | None = None) -> ToolResult:
  return ToolResult(False, [], [], False, sql, error)


def requireText(arguments: dict, name: str) -> str:
  value = arguments.get(name)
  if not isinstance(value, str) or not value.strip():
    raise ToolArgumentError(f"缺少參數 {name}，或不是文字")
  return value.strip()


def optionalText(arguments: dict, name: str) -> str | None:
  value = arguments.get(name)
  if value is None or (isinstance(value, str) and not value.strip()):
    return None
  if not isinstance(value, str):
    raise ToolArgumentError(f"參數 {name} 要是文字")
  return value.strip()


def parseRange(arguments: dict) -> tuple[datetime, datetime]:
  bounds = []
  for name in ("start", "end"):
    text = requireText(arguments, name)
    try:
      bounds.append(datetime.fromisoformat(text))
    except ValueError:
      raise ToolArgumentError(f"{name} 的格式要是 YYYY-MM-DD HH:MM，收到：{text}")
    # 沙盒的時間欄位沒有時區：帶時區的值無法和沒帶的比較，跟資料表比也會依 session 時區偏掉
    if bounds[-1].tzinfo is not None:
      raise ToolArgumentError(f"{name} 不要帶時區，用 YYYY-MM-DD HH:MM，收到：{text}")
  if bounds[1] < bounds[0]:
    raise ToolArgumentError("end 不能早於 start")
  return bounds[0], bounds[1]


def runSql(conn: Connection, arguments: dict) -> ToolResult:
  sql = sqlguard.extractSql(requireText(arguments, "sql"))
  try:
    sqlguard.validateSql(sql)
    columns, rows, truncated = sandbox.runQuery(conn, sql)
  except (sqlguard.UnsafeSqlError, psycopg.Error) as error:
    return failed(describeSqlError(error), sql)
  return ToolResult(True, columns, rows, truncated, sql, None)


def runFixed(conn: Connection, sql: str, params: dict, dropColumns: int = 0) -> ToolResult:
  try:
    columns, rows, truncated = sandbox.runQuery(conn, sql, params)
  except psycopg.Error as error:
    return failed(describeSqlError(error))
  if dropColumns:
    columns, rows = columns[:-dropColumns], [row[:-dropColumns] for row in rows]
  return ToolResult(True, columns, rows, truncated, None, None)


def findAvailablePeople(conn: Connection, arguments: dict) -> ToolResult:
  start, end = parseRange(arguments)
  params = {"start": start, "end": end, "department": optionalText(arguments, "department")}
  # employee_no 只用來排序，不給模型和使用者看
  return runFixed(conn, availableSql, params, dropColumns=1)


def getBusyPeriods(conn: Connection, arguments: dict) -> ToolResult:
  start, end = parseRange(arguments)
  employee, resource = optionalText(arguments, "employee"), optionalText(arguments, "resource")
  if employee and resource:
    raise ToolArgumentError("employee 和 resource 只能擇一")
  if resource:
    return runFixed(conn, resourceBusySql, {"start": start, "end": end, "resource": resource})
  return runFixed(conn, employeeBusySql, {"start": start, "end": end, "employee": employee})


handlers = {"run_sql": runSql, "find_available_people": findAvailablePeople, "get_busy_periods": getBusyPeriods}


def executeTool(conn: Connection, name: str, arguments: dict | None) -> ToolResult:
  handler = handlers.get(name)
  if handler is None:
    return failed(f"沒有 {name} 這個工具，只能用 {', '.join(handlers)}")
  if not isinstance(arguments, dict):
    return failed("參數不是合法的 JSON 物件")
  try:
    return handler(conn, arguments)
  except ToolArgumentError as error:
    return failed(str(error))


def formatForModel(result: ToolResult) -> str:
  if not result.ok:
    return f"錯誤：{result.error}"
  return json.dumps({
    "columns": result.columns, "rows": result.rows[:modelRowLimit], "rowCount": len(result.rows), "truncated": result.truncated,
  }, ensure_ascii=False)
