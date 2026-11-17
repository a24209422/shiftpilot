from datetime import date

import pytest

import db


@pytest.fixture
def dbPath(tmp_path):
  path = tmp_path / "test.db"
  db.initDb(path)
  return path


@pytest.fixture
def personId(dbPath):
  return db.addResource(dbPath, "王小明", "person")


def testAddEventThenListByDate(dbPath, personId):
  db.addEvent(dbPath, "週會", "meeting", personId, "2026-11-17 10:00", "2026-11-17 11:00")
  db.addEvent(dbPath, "早班", "shift", personId, "2026-11-20 08:00", "2026-11-20 16:00")

  events = db.listEvents(dbPath, date(2026, 11, 17), date(2026, 11, 18))

  assert [event["title"] for event in events] == ["週會"]
  assert events[0]["resource_name"] == "王小明"


def testOverlappingEventRaisesConflict(dbPath, personId):
  db.addEvent(dbPath, "週會", "meeting", personId, "2026-11-17 10:00", "2026-11-17 11:00")

  with pytest.raises(db.ScheduleConflictError) as excInfo:
    db.addEvent(dbPath, "面談", "meeting", personId, "2026-11-17 10:30", "2026-11-17 11:30")

  assert excInfo.value.conflicts[0]["title"] == "週會"


def testBackToBackEventsDoNotConflict(dbPath, personId):
  db.addEvent(dbPath, "週會", "meeting", personId, "2026-11-17 10:00", "2026-11-17 11:00")
  db.addEvent(dbPath, "面談", "meeting", personId, "2026-11-17 11:00", "2026-11-17 12:00")

  assert len(db.listEvents(dbPath, date(2026, 11, 17), date(2026, 11, 17))) == 2


def testSameTimeOnDifferentResourceIsAllowed(dbPath, personId):
  roomId = db.addResource(dbPath, "A 會議室", "room")
  db.addEvent(dbPath, "週會", "meeting", personId, "2026-11-17 10:00", "2026-11-17 11:00")
  db.addEvent(dbPath, "週會", "meeting", roomId, "2026-11-17 10:00", "2026-11-17 11:00")

  assert len(db.listEvents(dbPath, date(2026, 11, 17), date(2026, 11, 17))) == 2


def testEndBeforeStartIsRejected(dbPath, personId):
  with pytest.raises(ValueError):
    db.addEvent(dbPath, "錯誤", "meeting", personId, "2026-11-17 11:00", "2026-11-17 10:00")


def testInvalidTimeFormatIsRejected(dbPath, personId):
  with pytest.raises(ValueError):
    db.addEvent(dbPath, "錯誤", "meeting", personId, "2026/11/17 10:00", "2026/11/17 11:00")


def testSeedDemoDataOnlyRunsOnce(dbPath):
  assert db.seedDemoData(dbPath, today=date(2026, 11, 17)) is True
  resourceCount = len(db.listResources(dbPath))

  assert db.seedDemoData(dbPath, today=date(2026, 11, 17)) is False
  assert len(db.listResources(dbPath)) == resourceCount
