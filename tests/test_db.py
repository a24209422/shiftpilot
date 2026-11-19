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
