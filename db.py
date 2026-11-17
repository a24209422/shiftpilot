"""排程資料庫操作。"""
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

baseDir = Path(__file__).parent
schemaPath = baseDir / "schema.sql"
timeFormat = "%Y-%m-%d %H:%M"


class ScheduleConflictError(Exception):
  def __init__(self, conflicts):
    super().__init__(f"與 {len(conflicts)} 筆既有排程時段重疊")
    self.conflicts = conflicts


@contextmanager
def openDb(dbPath):
  # 每次操作都開關連線：Streamlit 每次互動都重跑整支 script，共用連線容易遇到跨執行緒問題
  conn = sqlite3.connect(dbPath)
  conn.row_factory = sqlite3.Row
  conn.execute("PRAGMA foreign_keys = ON")
  try:
    yield conn
    conn.commit()
  finally:
    conn.close()


def openReadOnly(dbPath):
  # mode=ro 讓 SQLite 本身拒絕寫入：就算 SQL 關鍵字檢查被繞過，LLM 產生的語句也改不到資料
  uri = "file:" + quote(Path(dbPath).resolve().as_posix(), safe="/:") + "?mode=ro"
  conn = sqlite3.connect(uri, uri=True)
  conn.execute("PRAGMA query_only = ON")
  return conn


def initDb(dbPath):
  with openDb(dbPath) as conn:
    conn.executescript(schemaPath.read_text(encoding="utf-8"))


def getSchemaText():
  return schemaPath.read_text(encoding="utf-8")


def toTimeText(value):
  if isinstance(value, datetime):
    return value.strftime(timeFormat)
  # 先 parse 一次，確保字串格式正確，否則字串比較時間會出錯
  return datetime.strptime(value, timeFormat).strftime(timeFormat)


def listResources(dbPath):
  with openDb(dbPath) as conn:
    rows = conn.execute("SELECT id, name, type, note FROM resources ORDER BY type, name").fetchall()
  return [dict(row) for row in rows]


def addResource(dbPath, name, resourceType, note=None):
  with openDb(dbPath) as conn:
    cursor = conn.execute(
      "INSERT INTO resources (name, type, note) VALUES (?, ?, ?)",
      (name.strip(), resourceType.strip(), note),
    )
    return cursor.lastrowid


def listEvents(dbPath, startDate, endDate, resourceId=None):
  sql = """
    SELECT e.id, e.title, e.category, e.start_at, e.end_at, r.name AS resource_name, r.type AS resource_type, e.note
    FROM events e JOIN resources r ON e.resource_id = r.id
    WHERE date(e.start_at) BETWEEN ? AND ?
  """
  params = [str(startDate), str(endDate)]
  if resourceId is not None:
    sql += " AND e.resource_id = ?"
    params.append(resourceId)
  sql += " ORDER BY e.start_at"
  with openDb(dbPath) as conn:
    rows = conn.execute(sql, params).fetchall()
  return [dict(row) for row in rows]


def findConflicts(dbPath, resourceId, startAt, endAt):
  # 兩段時間重疊的條件：A 開始 < B 結束 且 A 結束 > B 開始；剛好接續（10:00-11:00 與 11:00-12:00）不算衝突
  with openDb(dbPath) as conn:
    rows = conn.execute(
      """
      SELECT id, title, start_at, end_at FROM events
      WHERE resource_id = ? AND start_at < ? AND end_at > ?
      ORDER BY start_at
      """,
      (resourceId, toTimeText(endAt), toTimeText(startAt)),
    ).fetchall()
  return [dict(row) for row in rows]


def addEvent(dbPath, title, category, resourceId, startAt, endAt, note=None):
  startText, endText = toTimeText(startAt), toTimeText(endAt)
  if endText <= startText:
    raise ValueError("結束時間必須晚於開始時間")
  conflicts = findConflicts(dbPath, resourceId, startText, endText)
  if conflicts:
    raise ScheduleConflictError(conflicts)
  with openDb(dbPath) as conn:
    cursor = conn.execute(
      "INSERT INTO events (title, category, start_at, end_at, resource_id, note) VALUES (?, ?, ?, ?, ?, ?)",
      (title.strip(), category.strip(), startText, endText, resourceId, note),
    )
    return cursor.lastrowid


def getVocabulary(dbPath):
  # 把資料裡實際出現的值告訴 LLM，小模型才不會自己編出不存在的分類或名稱
  with openDb(dbPath) as conn:
    categories = [row[0] for row in conn.execute("SELECT DISTINCT category FROM events ORDER BY category")]
    resourceTypes = [row[0] for row in conn.execute("SELECT DISTINCT type FROM resources ORDER BY type")]
    resourceNames = [row[0] for row in conn.execute("SELECT name FROM resources ORDER BY name LIMIT 100")]
  return {"categories": categories, "resourceTypes": resourceTypes, "resourceNames": resourceNames}


def runReadOnlyQuery(dbPath, sql, maxRows=200):
  conn = openReadOnly(dbPath)
  try:
    cursor = conn.execute(sql)
    columns = [column[0] for column in cursor.description or []]
    rows = cursor.fetchmany(maxRows)
  finally:
    conn.close()
  return columns, [tuple(row) for row in rows]


def seedDemoData(dbPath, today=None):
  """資料庫是空的才塞示範資料；日期以今天為基準，讓「明天」「下週」這類問題查得到東西。"""
  with openDb(dbPath) as conn:
    if conn.execute("SELECT COUNT(*) FROM resources").fetchone()[0] > 0:
      return False

  today = today or date.today()
  monday = today - timedelta(days=today.weekday())
  resourceIds = {}
  for name, resourceType in [
    ("王小明", "person"), ("李小華", "person"), ("陳大文", "person"),
    ("A 會議室", "room"), ("B 會議室", "room"), ("投影機", "equipment"),
  ]:
    resourceIds[name] = addResource(dbPath, name, resourceType)

  demoEvents = [
    # (標題, 分類, 資源, 距離本週一的天數, 開始, 結束)
    ("週會", "meeting", "A 會議室", 0, "10:00", "11:00"),
    ("週會", "meeting", "A 會議室", 7, "10:00", "11:00"),
    ("客戶簡報", "meeting", "B 會議室", 2, "14:00", "15:30"),
    ("客戶簡報", "meeting", "王小明", 2, "14:00", "15:30"),
    ("早班", "shift", "李小華", 1, "08:00", "16:00"),
    ("早班", "shift", "李小華", 3, "08:00", "16:00"),
    ("早班", "shift", "李小華", 8, "08:00", "16:00"),
    ("晚班", "shift", "陳大文", 1, "16:00", "23:00"),
    ("晚班", "shift", "陳大文", 5, "16:00", "23:00"),
    ("晚班", "shift", "陳大文", 9, "16:00", "23:00"),
    ("撰寫季報", "task", "王小明", 4, "09:00", "12:00"),
    ("一對一面談", "meeting", "陳大文", 8, "15:00", "15:30"),
    ("投影機借用", "booking", "投影機", 9, "13:00", "17:00"),
    ("產品 demo", "meeting", "B 會議室", 10, "10:00", "12:00"),
    ("產品 demo", "meeting", "王小明", 10, "10:00", "12:00"),
  ]
  for title, category, resourceName, dayOffset, startTime, endTime in demoEvents:
    day = (monday + timedelta(days=dayOffset)).isoformat()
    addEvent(dbPath, title, category, resourceIds[resourceName], f"{day} {startTime}", f"{day} {endTime}")
  return True
