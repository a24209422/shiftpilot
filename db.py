"""排程資料庫操作（PostgreSQL）。"""
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

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
def openDb(databaseUrl):
  # 每次操作都開關連線：Streamlit 每次互動都重跑整支 script，共用連線容易遇到跨執行緒問題
  # psycopg 的連線離開 with 時，成功就 commit、發生例外就 rollback
  with psycopg.connect(databaseUrl, row_factory=dict_row) as conn:
    yield conn


@contextmanager
def temporarySchema(databaseUrl, prefix):
  """建立一個用完就刪的 schema，回傳只看得到它的連線字串。給測試與評測用，不會碰到其他資料。"""
  schemaName = f"{prefix}_{uuid.uuid4().hex[:8]}"
  identifier = sql.Identifier(schemaName)
  with psycopg.connect(databaseUrl, autocommit=True) as conn:
    conn.execute(sql.SQL("CREATE SCHEMA {}").format(identifier))
  try:
    # 用 search_path 把連線限制在這個 schema，程式裡的 SQL 不用加 schema 名稱
    yield make_conninfo(databaseUrl, options=f"-c search_path={schemaName}")
  finally:
    with psycopg.connect(databaseUrl, autocommit=True) as conn:
      conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(identifier))


def initDb(databaseUrl):
  with openDb(databaseUrl) as conn:
    # 不帶參數時 psycopg 允許一次送出多句 SQL，整份 schema.sql 可以直接執行
    conn.execute(schemaPath.read_text(encoding="utf-8"))


def getLlmSchemaText():
  # 給模型看的不是完整的建表語法，而是只有 view 和 resources 的精簡說明
  return llmSchemaPath.read_text(encoding="utf-8")


def toDateTime(value):
  if isinstance(value, datetime):
    return value
  # 字串要符合固定格式，打錯格式（例如 2026/11/17）時在這裡就擋下來
  return datetime.strptime(value, timeFormat)


def listResources(databaseUrl):
  with openDb(databaseUrl) as conn:
    return conn.execute("SELECT id, name, type, note FROM resources ORDER BY type, name").fetchall()


def addResource(databaseUrl, name, resourceType, note=None):
  with openDb(databaseUrl) as conn:
    row = conn.execute(
      "INSERT INTO resources (name, type, note) VALUES (%s, %s, %s) RETURNING id",
      (name.strip(), resourceType.strip(), note),
    ).fetchone()
  return row["id"]


def listEvents(databaseUrl, startDate, endDate, resourceId=None):
  query = f"""
    SELECT e.id, e.title, e.category, e.start_at, e.end_at, e.note, r.name AS resource_name
    {eventResourceJoin}
    WHERE e.start_at::date BETWEEN %s AND %s
  """
  params = [startDate, endDate]
  if resourceId is not None:
    # 用子查詢篩選而不是 WHERE er.resource_id = %s：篩出來的排程才會帶出它全部的資源，而不是只剩被篩選的那一個
    query += " AND e.id IN (SELECT event_id FROM event_resources WHERE resource_id = %s)"
    params.append(resourceId)
  query += " ORDER BY e.start_at, e.id, er.position"
  with openDb(databaseUrl) as conn:
    rows = conn.execute(query, params).fetchall()

  events = {}
  for row in rows:
    event = events.setdefault(row["id"], {
      "id": row["id"], "title": row["title"], "category": row["category"],
      "start_at": row["start_at"], "end_at": row["end_at"], "resource_names": [], "note": row["note"],
    })
    event["resource_names"].append(row["resource_name"])
  return list(events.values())


def findConflicts(databaseUrl, resourceIds, startAt, endAt):
  # 兩段時間重疊的條件：A 開始 < B 結束 且 A 結束 > B 開始；剛好接續（10:00-11:00 與 11:00-12:00）不算衝突
  with openDb(databaseUrl) as conn:
    return conn.execute(
      f"""
      SELECT e.id, e.title, e.start_at, e.end_at, r.name AS resource_name
      {eventResourceJoin}
      WHERE er.resource_id = ANY(%s) AND e.start_at < %s AND e.end_at > %s
      ORDER BY e.start_at, r.name
      """,
      (list(resourceIds), toDateTime(endAt), toDateTime(startAt)),
    ).fetchall()


def addEvent(databaseUrl, title, category, resourceIds, startAt, endAt, note=None):
  startAt, endAt = toDateTime(startAt), toDateTime(endAt)
  if endAt <= startAt:
    raise ValueError("結束時間必須晚於開始時間")
  # 去掉重複但保留順序：同一個資源選兩次會違反 event_resources 的主鍵
  uniqueResourceIds = list(dict.fromkeys(resourceIds))
  if not uniqueResourceIds:
    raise ValueError("排程至少要有一個資源")
  # 任何一個資源撞期就整筆不新增，不做「只排沒撞期的那幾個」
  conflicts = findConflicts(databaseUrl, uniqueResourceIds, startAt, endAt)
  if conflicts:
    raise ScheduleConflictError(conflicts)
  # 排程和它的資源寫在同一個交易：中途失敗就整筆不存，不會留下沒有資源的排程
  with openDb(databaseUrl) as conn:
    eventId = conn.execute(
      "INSERT INTO events (title, category, start_at, end_at, note) VALUES (%s, %s, %s, %s, %s) RETURNING id",
      (title.strip(), category.strip(), startAt, endAt, note),
    ).fetchone()["id"]
    with conn.cursor() as cursor:
      cursor.executemany(
        "INSERT INTO event_resources (event_id, resource_id, position) VALUES (%s, %s, %s)",
        [(eventId, resourceId, position) for position, resourceId in enumerate(uniqueResourceIds)],
      )
  return eventId


def getVocabulary(databaseUrl):
  # 把資料裡實際出現的值告訴 LLM，小模型才不會自己編出不存在的分類或名稱
  with openDb(databaseUrl) as conn:
    categories = [row["category"] for row in conn.execute("SELECT DISTINCT category FROM events ORDER BY category")]
    resourceTypes = [row["type"] for row in conn.execute("SELECT DISTINCT type FROM resources ORDER BY type")]
    resourceNames = [row["name"] for row in conn.execute("SELECT name FROM resources ORDER BY name LIMIT 100")]
  return {"categories": categories, "resourceTypes": resourceTypes, "resourceNames": resourceNames}


def runReadOnlyQuery(databaseUrl, query, maxRows=200):
  with psycopg.connect(databaseUrl) as conn:
    # read-only transaction 讓 PostgreSQL 本身拒絕寫入：就算 SQL 關鍵字檢查被繞過，LLM 產生的語句也改不到資料
    conn.read_only = True
    cursor = conn.execute(query)
    columns = [column.name for column in cursor.description or []]
    rows = cursor.fetchmany(maxRows)
  return columns, rows


def seedDemoData(databaseUrl, today=None):
  """資料庫是空的才塞示範資料；日期以今天為基準，讓「明天」「下週」這類問題查得到東西。"""
  with openDb(databaseUrl) as conn:
    if conn.execute("SELECT EXISTS (SELECT 1 FROM resources) AS has_data").fetchone()["has_data"]:
      return False

  today = today or date.today()
  monday = today - timedelta(days=today.weekday())
  resourceIds = {}
  for name, resourceType in [
    ("王小明", "person"), ("李小華", "person"), ("陳大文", "person"),
    ("A 會議室", "room"), ("B 會議室", "room"), ("投影機", "equipment"),
  ]:
    resourceIds[name] = addResource(databaseUrl, name, resourceType)

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
    addEvent(databaseUrl, title, category, eventResourceIds, f"{day} {startTime}", f"{day} {endTime}")
  return True
