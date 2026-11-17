"""排程資料庫操作。"""
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

baseDir = Path(__file__).parent
schemaPath = baseDir / "schema.sql"
llmSchemaPath = baseDir / "llm_schema.sql"
timeFormat = "%Y-%m-%d %H:%M"
eventResourceJoin = """
  FROM events e
  JOIN event_resources er ON er.event_id = e.id
  JOIN resources r ON r.id = er.resource_id
"""


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


def getLlmSchemaText():
  # 給模型看的不是完整的建表語法，而是只有 view 和 resources 的精簡說明
  return llmSchemaPath.read_text(encoding="utf-8")


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
  sql = f"""
    SELECT e.id, e.title, e.category, e.start_at, e.end_at, e.note, r.name AS resource_name
    {eventResourceJoin}
    WHERE date(e.start_at) BETWEEN ? AND ?
  """
  params = [str(startDate), str(endDate)]
  if resourceId is not None:
    # 用子查詢篩選而不是 WHERE er.resource_id = ?：篩出來的排程才會帶出它全部的資源，而不是只剩被篩選的那一個
    sql += " AND e.id IN (SELECT event_id FROM event_resources WHERE resource_id = ?)"
    params.append(resourceId)
  # er.rowid 是寫入順序，資源會照新增排程時選的順序排列
  sql += " ORDER BY e.start_at, e.id, er.rowid"
  with openDb(dbPath) as conn:
    rows = conn.execute(sql, params).fetchall()

  events = {}
  for row in rows:
    event = events.setdefault(row["id"], {
      "id": row["id"], "title": row["title"], "category": row["category"],
      "start_at": row["start_at"], "end_at": row["end_at"], "resource_names": [], "note": row["note"],
    })
    event["resource_names"].append(row["resource_name"])
  return list(events.values())


def findConflicts(dbPath, resourceIds, startAt, endAt):
  placeholders = ", ".join("?" * len(resourceIds))
  # 兩段時間重疊的條件：A 開始 < B 結束 且 A 結束 > B 開始；剛好接續（10:00-11:00 與 11:00-12:00）不算衝突
  with openDb(dbPath) as conn:
    rows = conn.execute(
      f"""
      SELECT e.id, e.title, e.start_at, e.end_at, r.name AS resource_name
      {eventResourceJoin}
      WHERE er.resource_id IN ({placeholders}) AND e.start_at < ? AND e.end_at > ?
      ORDER BY e.start_at, r.name
      """,
      (*resourceIds, toTimeText(endAt), toTimeText(startAt)),
    ).fetchall()
  return [dict(row) for row in rows]


def addEvent(dbPath, title, category, resourceIds, startAt, endAt, note=None):
  startText, endText = toTimeText(startAt), toTimeText(endAt)
  if endText <= startText:
    raise ValueError("結束時間必須晚於開始時間")
  # 去掉重複但保留順序：同一個資源選兩次會違反 event_resources 的主鍵
  uniqueResourceIds = list(dict.fromkeys(resourceIds))
  if not uniqueResourceIds:
    raise ValueError("排程至少要有一個資源")
  # 任何一個資源撞期就整筆不新增，不做「只排沒撞期的那幾個」
  conflicts = findConflicts(dbPath, uniqueResourceIds, startText, endText)
  if conflicts:
    raise ScheduleConflictError(conflicts)
  # 排程和它的資源寫在同一個交易：中途失敗就整筆不存，不會留下沒有資源的排程
  with openDb(dbPath) as conn:
    cursor = conn.execute(
      "INSERT INTO events (title, category, start_at, end_at, note) VALUES (?, ?, ?, ?, ?)",
      (title.strip(), category.strip(), startText, endText, note),
    )
    conn.executemany(
      "INSERT INTO event_resources (event_id, resource_id) VALUES (?, ?)",
      [(cursor.lastrowid, resourceId) for resourceId in uniqueResourceIds],
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

  weeklyMeetingAttendees = ["A 會議室", "王小明", "李小華", "陳大文"]
  demoEvents = [
    # (標題, 分類, 資源, 距離本週一的天數, 開始, 結束)
    ("週會", "meeting", weeklyMeetingAttendees, 0, "10:00", "11:00"),
    ("週會", "meeting", weeklyMeetingAttendees, 7, "10:00", "11:00"),
    ("客戶簡報", "meeting", ["B 會議室", "王小明"], 2, "14:00", "15:30"),
    ("早班", "shift", ["李小華"], 1, "08:00", "16:00"),
    ("早班", "shift", ["李小華"], 3, "08:00", "16:00"),
    ("早班", "shift", ["李小華"], 8, "08:00", "16:00"),
    ("晚班", "shift", ["陳大文"], 1, "16:00", "23:00"),
    ("晚班", "shift", ["陳大文"], 5, "16:00", "23:00"),
    ("晚班", "shift", ["陳大文"], 9, "16:00", "23:00"),
    ("撰寫季報", "task", ["王小明"], 4, "09:00", "12:00"),
    ("一對一面談", "meeting", ["陳大文"], 8, "15:00", "15:30"),
    ("投影機借用", "booking", ["投影機"], 9, "13:00", "17:00"),
    ("產品 demo", "meeting", ["B 會議室", "王小明"], 10, "10:00", "12:00"),
  ]
  for title, category, resourceNames, dayOffset, startTime, endTime in demoEvents:
    day = (monday + timedelta(days=dayOffset)).isoformat()
    eventResourceIds = [resourceIds[name] for name in resourceNames]
    addEvent(dbPath, title, category, eventResourceIds, f"{day} {startTime}", f"{day} {endTime}")
  return True
