import sqlite3
from datetime import date

import pytest

import db

day = date(2026, 11, 17)


@pytest.fixture
def dbPath(tmp_path):
  path = tmp_path / "test.db"
  db.initDb(path)
  return path


@pytest.fixture
def personId(dbPath):
  return db.addResource(dbPath, "王小明", "person")


@pytest.fixture
def roomId(dbPath):
  return db.addResource(dbPath, "A 會議室", "room")


def testAddEventThenListByDate(dbPath, personId):
  db.addEvent(dbPath, "週會", "meeting", [personId], "2026-11-17 10:00", "2026-11-17 11:00")
  db.addEvent(dbPath, "早班", "shift", [personId], "2026-11-20 08:00", "2026-11-20 16:00")

  events = db.listEvents(dbPath, date(2026, 11, 17), date(2026, 11, 18))

  assert [event["title"] for event in events] == ["週會"]
  assert events[0]["resource_names"] == ["王小明"]


def testEventWithSeveralResourcesIsStoredOnce(dbPath, personId, roomId):
  db.addEvent(dbPath, "週會", "meeting", [personId, roomId], "2026-11-17 10:00", "2026-11-17 11:00")

  events = db.listEvents(dbPath, day, day)
  _, eventCount = db.runReadOnlyQuery(dbPath, "SELECT COUNT(*) FROM events")

  assert eventCount == [(1,)]
  assert len(events) == 1
  assert events[0]["resource_names"] == ["王小明", "A 會議室"]


def testEventDetailsViewHasOneRowPerResource(dbPath, personId, roomId):
  db.addEvent(dbPath, "週會", "meeting", [personId, roomId], "2026-11-17 10:00", "2026-11-17 11:00")

  _, rows = db.runReadOnlyQuery(
    dbPath,
    "SELECT event_id, title, category, start_at, end_at, resource_name, resource_type "
    "FROM event_details ORDER BY resource_type",
  )

  assert rows == [
    (1, "週會", "meeting", "2026-11-17 10:00", "2026-11-17 11:00", "王小明", "person"),
    (1, "週會", "meeting", "2026-11-17 10:00", "2026-11-17 11:00", "A 會議室", "room"),
  ]


def testListEventsFilteredByResourceStillShowsAllResources(dbPath, personId, roomId):
  db.addEvent(dbPath, "週會", "meeting", [personId, roomId], "2026-11-17 10:00", "2026-11-17 11:00")
  db.addEvent(dbPath, "撰寫季報", "task", [personId], "2026-11-17 13:00", "2026-11-17 14:00")

  events = db.listEvents(dbPath, day, day, resourceId=roomId)

  assert [event["title"] for event in events] == ["週會"]
  assert events[0]["resource_names"] == ["王小明", "A 會議室"]


def testOverlappingEventRaisesConflict(dbPath, personId):
  db.addEvent(dbPath, "週會", "meeting", [personId], "2026-11-17 10:00", "2026-11-17 11:00")

  with pytest.raises(db.ScheduleConflictError) as excInfo:
    db.addEvent(dbPath, "面談", "meeting", [personId], "2026-11-17 10:30", "2026-11-17 11:30")

  assert excInfo.value.conflicts[0]["title"] == "週會"
  assert excInfo.value.conflicts[0]["resource_name"] == "王小明"


def testConflictOnAnyResourceRejectsWholeEvent(dbPath, personId, roomId):
  db.addEvent(dbPath, "週會", "meeting", [roomId], "2026-11-17 10:00", "2026-11-17 11:00")

  with pytest.raises(db.ScheduleConflictError) as excInfo:
    db.addEvent(dbPath, "面談", "meeting", [personId, roomId], "2026-11-17 10:30", "2026-11-17 11:30")

  assert [conflict["resource_name"] for conflict in excInfo.value.conflicts] == ["A 會議室"]
  # 人沒有撞期，但整筆都不能新增，否則會留下只排到一半資源的排程
  assert db.listEvents(dbPath, day, day, resourceId=personId) == []


def testBackToBackEventsDoNotConflict(dbPath, personId):
  db.addEvent(dbPath, "週會", "meeting", [personId], "2026-11-17 10:00", "2026-11-17 11:00")
  db.addEvent(dbPath, "面談", "meeting", [personId], "2026-11-17 11:00", "2026-11-17 12:00")

  assert len(db.listEvents(dbPath, day, day)) == 2


def testSameTimeOnDifferentResourceIsAllowed(dbPath, personId, roomId):
  db.addEvent(dbPath, "撰寫季報", "task", [personId], "2026-11-17 10:00", "2026-11-17 11:00")
  db.addEvent(dbPath, "週會", "meeting", [roomId], "2026-11-17 10:00", "2026-11-17 11:00")

  assert len(db.listEvents(dbPath, day, day)) == 2


def testEndBeforeStartIsRejected(dbPath, personId):
  with pytest.raises(ValueError):
    db.addEvent(dbPath, "錯誤", "meeting", [personId], "2026-11-17 11:00", "2026-11-17 10:00")


def testInvalidTimeFormatIsRejected(dbPath, personId):
  with pytest.raises(ValueError):
    db.addEvent(dbPath, "錯誤", "meeting", [personId], "2026/11/17 10:00", "2026/11/17 11:00")


def testEventNeedsAtLeastOneResource(dbPath):
  with pytest.raises(ValueError):
    db.addEvent(dbPath, "週會", "meeting", [], "2026-11-17 10:00", "2026-11-17 11:00")


def testRepeatedResourceIsLinkedOnlyOnce(dbPath, personId):
  db.addEvent(dbPath, "週會", "meeting", [personId, personId], "2026-11-17 10:00", "2026-11-17 11:00")

  assert db.listEvents(dbPath, day, day)[0]["resource_names"] == ["王小明"]


def testUnknownResourceLeavesNoHalfSavedEvent(dbPath, personId):
  with pytest.raises(sqlite3.IntegrityError):
    db.addEvent(dbPath, "週會", "meeting", [personId, 999], "2026-11-17 10:00", "2026-11-17 11:00")

  assert db.listEvents(dbPath, day, day) == []
  assert db.runReadOnlyQuery(dbPath, "SELECT COUNT(*) FROM events")[1] == [(0,)]


def testSeedDemoDataOnlyRunsOnce(dbPath):
  assert db.seedDemoData(dbPath, today=day) is True
  resourceCount = len(db.listResources(dbPath))

  assert db.seedDemoData(dbPath, today=day) is False
  assert len(db.listResources(dbPath)) == resourceCount


def testSeedDemoDataIncludesEventsWithSeveralResources(dbPath):
  db.seedDemoData(dbPath, today=day)

  events = db.listEvents(dbPath, date(2026, 11, 16), date(2026, 11, 29))

  assert any(len(event["resource_names"]) > 1 for event in events)


def testLlmSchemaHidesTheJoinTable():
  # 模型只該看到攤平的 view；看到 event_resources 就會想自己寫兩次 JOIN
  schemaText = db.getLlmSchemaText()

  assert "event_details" in schemaText
  assert "resources" in schemaText
  assert "event_resources" not in schemaText
