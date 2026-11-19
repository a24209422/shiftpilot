from datetime import date, datetime

import psycopg
import pytest

import db

day = date(2026, 11, 17)


@pytest.fixture
def personId(databaseUrl):
  return db.addResource(databaseUrl, "王小明", "person")


@pytest.fixture
def roomId(databaseUrl):
  return db.addResource(databaseUrl, "A 會議室", "room")


def testAddEventThenListByDate(databaseUrl, personId):
  db.addEvent(databaseUrl, "週會", "meeting", [personId], "2026-11-17 10:00", "2026-11-17 11:00")
  db.addEvent(databaseUrl, "早班", "shift", [personId], "2026-11-20 08:00", "2026-11-20 16:00")

  events = db.listEvents(databaseUrl, date(2026, 11, 17), date(2026, 11, 18))

  assert [event["title"] for event in events] == ["週會"]
  assert events[0]["resource_names"] == ["王小明"]


def testEventWithSeveralResourcesIsStoredOnce(databaseUrl, personId, roomId):
  db.addEvent(databaseUrl, "週會", "meeting", [personId, roomId], "2026-11-17 10:00", "2026-11-17 11:00")

  events = db.listEvents(databaseUrl, day, day)
  _, eventCount = db.runReadOnlyQuery(databaseUrl, "SELECT COUNT(*) FROM events")

  assert eventCount == [(1,)]
  assert len(events) == 1
  assert events[0]["resource_names"] == ["王小明", "A 會議室"]


def testEventDetailsViewHasOneRowPerResource(databaseUrl, personId, roomId):
  db.addEvent(databaseUrl, "週會", "meeting", [personId, roomId], "2026-11-17 10:00", "2026-11-17 11:00")

  _, rows = db.runReadOnlyQuery(
    databaseUrl,
    "SELECT event_id, title, category, start_at, end_at, resource_name, resource_type "
    "FROM event_details ORDER BY resource_type",
  )

  startAt, endAt = datetime(2026, 11, 17, 10, 0), datetime(2026, 11, 17, 11, 0)
  assert rows == [
    (1, "週會", "meeting", startAt, endAt, "王小明", "person"),
    (1, "週會", "meeting", startAt, endAt, "A 會議室", "room"),
  ]


def testListEventsFilteredByResourceStillShowsAllResources(databaseUrl, personId, roomId):
  db.addEvent(databaseUrl, "週會", "meeting", [personId, roomId], "2026-11-17 10:00", "2026-11-17 11:00")
  db.addEvent(databaseUrl, "撰寫季報", "task", [personId], "2026-11-17 13:00", "2026-11-17 14:00")

  events = db.listEvents(databaseUrl, day, day, resourceId=roomId)

  assert [event["title"] for event in events] == ["週會"]
  assert events[0]["resource_names"] == ["王小明", "A 會議室"]


def testOverlappingEventRaisesConflict(databaseUrl, personId):
  db.addEvent(databaseUrl, "週會", "meeting", [personId], "2026-11-17 10:00", "2026-11-17 11:00")

  with pytest.raises(db.ScheduleConflictError) as excInfo:
    db.addEvent(databaseUrl, "面談", "meeting", [personId], "2026-11-17 10:30", "2026-11-17 11:30")

  assert excInfo.value.conflicts[0]["title"] == "週會"
  assert excInfo.value.conflicts[0]["resource_name"] == "王小明"


def testConflictOnAnyResourceRejectsWholeEvent(databaseUrl, personId, roomId):
  db.addEvent(databaseUrl, "週會", "meeting", [roomId], "2026-11-17 10:00", "2026-11-17 11:00")

  with pytest.raises(db.ScheduleConflictError) as excInfo:
    db.addEvent(databaseUrl, "面談", "meeting", [personId, roomId], "2026-11-17 10:30", "2026-11-17 11:30")

  assert [conflict["resource_name"] for conflict in excInfo.value.conflicts] == ["A 會議室"]
  # 人沒有撞期，但整筆都不能新增，否則會留下只排到一半資源的排程
  assert db.listEvents(databaseUrl, day, day, resourceId=personId) == []


def testBackToBackEventsDoNotConflict(databaseUrl, personId):
  db.addEvent(databaseUrl, "週會", "meeting", [personId], "2026-11-17 10:00", "2026-11-17 11:00")
  db.addEvent(databaseUrl, "面談", "meeting", [personId], "2026-11-17 11:00", "2026-11-17 12:00")

  assert len(db.listEvents(databaseUrl, day, day)) == 2


def testSameTimeOnDifferentResourceIsAllowed(databaseUrl, personId, roomId):
  db.addEvent(databaseUrl, "撰寫季報", "task", [personId], "2026-11-17 10:00", "2026-11-17 11:00")
  db.addEvent(databaseUrl, "週會", "meeting", [roomId], "2026-11-17 10:00", "2026-11-17 11:00")

  assert len(db.listEvents(databaseUrl, day, day)) == 2


def testEndBeforeStartIsRejected(databaseUrl, personId):
  with pytest.raises(ValueError):
    db.addEvent(databaseUrl, "錯誤", "meeting", [personId], "2026-11-17 11:00", "2026-11-17 10:00")


def testInvalidTimeFormatIsRejected(databaseUrl, personId):
  with pytest.raises(ValueError):
    db.addEvent(databaseUrl, "錯誤", "meeting", [personId], "2026/11/17 10:00", "2026/11/17 11:00")


def testEventNeedsAtLeastOneResource(databaseUrl):
  with pytest.raises(ValueError):
    db.addEvent(databaseUrl, "週會", "meeting", [], "2026-11-17 10:00", "2026-11-17 11:00")


def testRepeatedResourceIsLinkedOnlyOnce(databaseUrl, personId):
  db.addEvent(databaseUrl, "週會", "meeting", [personId, personId], "2026-11-17 10:00", "2026-11-17 11:00")

  assert db.listEvents(databaseUrl, day, day)[0]["resource_names"] == ["王小明"]


def testUnknownResourceLeavesNoHalfSavedEvent(databaseUrl, personId):
  with pytest.raises(psycopg.errors.ForeignKeyViolation):
    db.addEvent(databaseUrl, "週會", "meeting", [personId, 999], "2026-11-17 10:00", "2026-11-17 11:00")

  assert db.listEvents(databaseUrl, day, day) == []
  assert db.runReadOnlyQuery(databaseUrl, "SELECT COUNT(*) FROM events")[1] == [(0,)]


def testSeedDemoDataOnlyRunsOnce(databaseUrl):
  assert db.seedDemoData(databaseUrl, today=day) is True
  resourceCount = len(db.listResources(databaseUrl))

  assert db.seedDemoData(databaseUrl, today=day) is False
  assert len(db.listResources(databaseUrl)) == resourceCount


def testSeedDemoDataIncludesEventsWithSeveralResources(databaseUrl):
  db.seedDemoData(databaseUrl, today=day)

  events = db.listEvents(databaseUrl, date(2026, 11, 16), date(2026, 11, 29))

  assert any(len(event["resource_names"]) > 1 for event in events)


def testLlmSchemaListsEveryRealColumn(databaseUrl):
  # 給模型看的說明是手寫的，實際的表多了欄位卻沒寫進去，模型就不知道它存在
  _, rows = db.runReadOnlyQuery(databaseUrl, """
    SELECT c.table_name, c.column_name
    FROM information_schema.columns c
    JOIN information_schema.tables t ON t.table_schema = c.table_schema AND t.table_name = c.table_name
    WHERE c.table_schema = current_schema() AND t.table_type = 'BASE TABLE'
  """)
  blocks = {block.split("(")[0].strip(): block for block in db.getLlmSchemaText().split("CREATE TABLE ")[1:]}

  assert "event_details" not in db.getLlmSchemaText()
  assert {table for table, _ in rows} == set(blocks)
  assert [(table, column) for table, column in rows if column not in blocks[table]] == []


overlappingApprovedLeaveSql = """
  SELECT l.id FROM leave_requests l
  JOIN employees em ON em.id = l.employee_id
  JOIN event_resources er ON er.resource_id = em.resource_id
  JOIN events e ON e.id = er.event_id
  WHERE l.status = 'approved' AND e.start_at < l.end_at AND e.end_at > l.start_at
"""


def countRows(databaseUrl, table):
  return db.runReadOnlyQuery(databaseUrl, f"SELECT COUNT(*) FROM {table}")[1][0][0]


def testAddOrganizationDataLinksPeopleDepartmentsAndRooms(databaseUrl, personId, roomId):
  db.addResource(databaseUrl, "李小華", "person")

  db.addOrganizationData(databaseUrl, {
    "departments": [("總經理室", None), ("營運部", "總經理室")],
    "employees": [
      ("王小明", "總經理室", "副總經理", None, "2019-03-01"),
      ("李小華", "營運部", "營運組長", "王小明", "2021-07-15"),
    ],
    "rooms": [("A 會議室", 10, 12, True)],
  })

  _, rows = db.runReadOnlyQuery(databaseUrl, """
    SELECT sub.name, boss.name, parentDept.name
    FROM employees e
    JOIN resources sub ON sub.id = e.resource_id
    JOIN employees bossEmployee ON bossEmployee.id = e.manager_id
    JOIN resources boss ON boss.id = bossEmployee.resource_id
    JOIN departments d ON d.id = e.department_id
    JOIN departments parentDept ON parentDept.id = d.parent_id
  """)
  _, roomRows = db.runReadOnlyQuery(databaseUrl, """
    SELECT r.name, rooms.floor, rooms.capacity, rooms.has_video_conference
    FROM rooms JOIN resources r ON r.id = rooms.resource_id
  """)
  assert rows == [("李小華", "王小明", "總經理室")]
  assert roomRows == [("A 會議室", 10, 12, True)]


def testAddOrganizationDataRejectsUnknownResourceAndSavesNothing(databaseUrl, personId):
  with pytest.raises(ValueError):
    db.addOrganizationData(databaseUrl, {
      "departments": [("營運部", None)],
      "employees": [("不存在的人", "營運部", "專員", None, "2024-01-01")],
    })

  # 部門先寫、員工後寫：員工失敗時部門也要一起回復，不能留下半套資料
  assert countRows(databaseUrl, "departments") == 0
  assert countRows(databaseUrl, "employees") == 0


def testSeedDemoDataFillsOrganizationTables(databaseUrl):
  db.seedDemoData(databaseUrl, today=day)

  assert countRows(databaseUrl, "departments") == 3
  assert countRows(databaseUrl, "employees") == 3
  assert countRows(databaseUrl, "rooms") == 2
  assert countRows(databaseUrl, "work_hours") == 5
  assert countRows(databaseUrl, "leave_requests") == 4
  assert countRows(databaseUrl, "holidays") >= 2


def testDemoApprovedLeaveDoesNotOverlapOwnEvents(databaseUrl):
  db.seedDemoData(databaseUrl, today=day)

  assert db.runReadOnlyQuery(databaseUrl, overlappingApprovedLeaveSql)[1] == []


def testInitDbTwiceKeepsDemoData(databaseUrl):
  # app 每次啟動都會執行 initDb，已經有資料的資料庫不能因此出錯或掉資料
  db.seedDemoData(databaseUrl, today=day)

  db.initDb(databaseUrl)

  assert countRows(databaseUrl, "employees") == 3
