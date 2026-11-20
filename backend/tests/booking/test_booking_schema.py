from datetime import datetime

import psycopg
import pytest

from app.infra.db import openDb
from tests.helpers import insertActor


def at(hour, minute=0, day=24):
  return datetime(2026, 11, day, hour, minute)


def insertResource(conn, name="A 會議室", kind="room", **extra):
  values = {"name": name, "kind": kind}
  values.update(extra)
  columns = ", ".join(values)
  placeholders = ", ".join(["%s"] * len(values))
  return conn.execute(f"INSERT INTO resources ({columns}) VALUES ({placeholders}) RETURNING id", list(values.values())).fetchone()["id"]


def insertEmployee(conn, employeeNo="E001"):
  departmentId = conn.execute("INSERT INTO departments (name) VALUES (%s) RETURNING id", (f"部門{employeeNo}",)).fetchone()["id"]
  return conn.execute(
    "INSERT INTO employees (employee_no, name, department_id, job_title, hired_on) VALUES (%s, '王', %s, '工程師', '2025-01-01') RETURNING id",
    (employeeNo, departmentId),
  ).fetchone()["id"]


def insertBooking(conn, userId, startAt, endAt, title="週會", status="confirmed"):
  return conn.execute(
    "INSERT INTO bookings (title, category, start_at, end_at, status, created_by) VALUES (%s, '會議', %s, %s, %s, %s) RETURNING id",
    (title, startAt, endAt, status, userId),
  ).fetchone()["id"]


def attach(conn, bookingId, resourceId):
  # 故意不給 during 與 is_active：由 trigger 從預約帶入
  conn.execute("INSERT INTO booking_resources (booking_id, resource_id) VALUES (%s, %s)", (bookingId, resourceId))


@pytest.fixture
def base(migratedUrl):
  with openDb(migratedUrl) as conn:
    userId = insertActor(conn).userId
    roomId = insertResource(conn)
  return migratedUrl, userId, roomId


def testExclusionRejectsOverlappingActiveBookings(base):
  url, userId, roomId = base
  with pytest.raises(psycopg.errors.ExclusionViolation):
    with openDb(url) as conn:
      attach(conn, insertBooking(conn, userId, at(10), at(11)), roomId)
      attach(conn, insertBooking(conn, userId, at(10, 30), at(11, 30)), roomId)


def testAdjacentBookingsAreAllowed(base):
  url, userId, roomId = base
  with openDb(url) as conn:
    attach(conn, insertBooking(conn, userId, at(10), at(11)), roomId)
    attach(conn, insertBooking(conn, userId, at(11), at(12)), roomId)
    assert conn.execute("SELECT count(*) AS n FROM booking_resources").fetchone()["n"] == 2


def testDifferentResourcesMayOverlap(base):
  url, userId, roomId = base
  with openDb(url) as conn:
    otherId = insertResource(conn, "B 會議室")
    attach(conn, insertBooking(conn, userId, at(10), at(11)), roomId)
    attach(conn, insertBooking(conn, userId, at(10), at(11)), otherId)


def testCancelledBookingDoesNotBlock(base):
  url, userId, roomId = base
  with openDb(url) as conn:
    first = insertBooking(conn, userId, at(10), at(11))
    attach(conn, first, roomId)
    conn.execute("UPDATE bookings SET status = 'cancelled' WHERE id = %s", (first,))
    attach(conn, insertBooking(conn, userId, at(10), at(11)), roomId)
    assert conn.execute("SELECT is_active FROM booking_resources WHERE booking_id = %s", (first,)).fetchone()["is_active"] is False


def testChangingBookingTimeSyncsDuring(base):
  url, userId, roomId = base
  with openDb(url) as conn:
    bookingId = insertBooking(conn, userId, at(10), at(11))
    attach(conn, bookingId, roomId)
    conn.execute("UPDATE bookings SET end_at = %s WHERE id = %s", (at(12), bookingId))
    during = conn.execute("SELECT during FROM booking_resources WHERE booking_id = %s", (bookingId,)).fetchone()["during"]
  assert (during.lower, during.upper) == (at(10), at(12))


def testMovingIntoConflictIsRejected(base):
  url, userId, roomId = base
  with pytest.raises(psycopg.errors.ExclusionViolation):
    with openDb(url) as conn:
      attach(conn, insertBooking(conn, userId, at(10), at(11)), roomId)
      moving = insertBooking(conn, userId, at(13), at(14))
      attach(conn, moving, roomId)
      conn.execute("UPDATE bookings SET start_at = %s, end_at = %s WHERE id = %s", (at(10, 30), at(11, 30), moving))


def testReactivatingCancelledBookingIntoConflictIsRejected(base):
  url, userId, roomId = base
  with pytest.raises(psycopg.errors.ExclusionViolation):
    with openDb(url) as conn:
      attach(conn, insertBooking(conn, userId, at(10), at(11)), roomId)
      cancelled = insertBooking(conn, userId, at(10), at(11), status="cancelled")
      attach(conn, cancelled, roomId)
      conn.execute("UPDATE bookings SET status = 'confirmed' WHERE id = %s", (cancelled,))


def testBookingMayCrossMidnight(base):
  url, userId, roomId = base
  with openDb(url) as conn:
    attach(conn, insertBooking(conn, userId, at(22), at(6, day=25)), roomId)
  with pytest.raises(psycopg.errors.ExclusionViolation):
    with openDb(url) as conn:
      attach(conn, insertBooking(conn, userId, at(5, day=25), at(7, day=25)), roomId)


def testSecondOrganizerRejected(base):
  url, userId, _ = base
  with pytest.raises(psycopg.errors.UniqueViolation):
    with openDb(url) as conn:
      bookingId = insertBooking(conn, userId, at(10), at(11))
      for number in ("E001", "E002"):
        conn.execute(
          "INSERT INTO booking_participants (booking_id, employee_id, role) VALUES (%s, %s, 'organizer')",
          (bookingId, insertEmployee(conn, number)),
        )


def testParticipantRoleIsRestricted(base):
  url, userId, _ = base
  with pytest.raises(psycopg.errors.CheckViolation):
    with openDb(url) as conn:
      bookingId = insertBooking(conn, userId, at(10), at(11))
      conn.execute(
        "INSERT INTO booking_participants (booking_id, employee_id, role) VALUES (%s, %s, 'guest')",
        (bookingId, insertEmployee(conn)),
      )


def testEndMustBeAfterStart(base):
  url, userId, _ = base
  with pytest.raises(psycopg.errors.CheckViolation):
    with openDb(url) as conn:
      insertBooking(conn, userId, at(11), at(11))


def testBlankTitleRejected(base):
  url, userId, _ = base
  with pytest.raises(psycopg.errors.CheckViolation):
    with openDb(url) as conn:
      insertBooking(conn, userId, at(10), at(11), title="   ")


def testResourceKindAndCapacityAreRestricted(base):
  url, _, _ = base
  with pytest.raises(psycopg.errors.CheckViolation):
    with openDb(url) as conn:
      insertResource(conn, "X", kind="person")
  with pytest.raises(psycopg.errors.CheckViolation):
    with openDb(url) as conn:
      insertResource(conn, "Y", capacity=0)


def testDirectUpdateOfBookingResourcesCannotDesyncIt(base):
  # 資料庫要保證不會不同步：就算有人手動改 booking_resources，也不能讓同一時段的資源被重複預約
  url, userId, roomId = base
  bookingId = None
  with openDb(url) as conn:
    bookingId = insertBooking(conn, userId, at(10), at(11))
    attach(conn, bookingId, roomId)
    conn.execute(
      "UPDATE booking_resources SET is_active = false, during = tsrange('2030-01-01', '2030-01-02') WHERE booking_id = %s", (bookingId,)
    )
    row = conn.execute("SELECT is_active, during FROM booking_resources WHERE booking_id = %s", (bookingId,)).fetchone()
  assert row["is_active"] is True and (row["during"].lower, row["during"].upper) == (at(10), at(11))
  with pytest.raises(psycopg.errors.ExclusionViolation):
    with openDb(url) as conn:
      attach(conn, insertBooking(conn, userId, at(10, 30), at(11, 30)), roomId)
