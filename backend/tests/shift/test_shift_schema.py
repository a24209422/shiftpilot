import psycopg
import pytest

from app.infra.db import openDb
from tests.helpers import insertActor


def insertEmployee(conn, employeeNo="E001"):
  departmentId = conn.execute("INSERT INTO departments (name) VALUES (%s) RETURNING id", (f"部門{employeeNo}",)).fetchone()["id"]
  return conn.execute(
    "INSERT INTO employees (employee_no, name, department_id, job_title, hired_on) VALUES (%s, '王', %s, '工程師', '2025-01-01') RETURNING id",
    (employeeNo, departmentId),
  ).fetchone()["id"]


def insertType(conn, code, start, end, breakStart=None, breakEnd=None, isDefault=False, isActive=True):
  return conn.execute(
    "INSERT INTO shift_types (code, name, start_time, end_time, break_start, break_end, is_default, is_active) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
    (code, f"班{code}", start, end, breakStart, breakEnd, isDefault, isActive),
  ).fetchone()["id"]


def expectViolation(conn, error, sql, params=()):
  with pytest.raises(error), conn.transaction():
    conn.execute(sql, params)


def testMigrationSeedsStandardDefaultShift(migratedUrl):
  with openDb(migratedUrl) as conn:
    rows = conn.execute("SELECT code, name, start_time::text, end_time::text, break_start::text, break_end::text, is_default FROM shift_types").fetchall()
  assert rows == [{
    "code": "standard", "name": "標準班", "start_time": "09:00:00", "end_time": "18:00:00",
    "break_start": "12:00:00", "break_end": "13:00:00", "is_default": True,
  }]


def testOnlyOneDefaultShift(migratedUrl):
  with openDb(migratedUrl) as conn:
    expectViolation(conn, psycopg.errors.UniqueViolation,
                    "INSERT INTO shift_types (code, name, start_time, end_time, is_default) VALUES ('x', '某班', '10:00', '19:00', true)")


def testDefaultShiftMustBeActive(migratedUrl):
  with openDb(migratedUrl) as conn:
    expectViolation(conn, psycopg.errors.CheckViolation, "UPDATE shift_types SET is_active = false WHERE code = 'standard'")


def testShiftTimesMustBeWholeHoursAndDiffer(migratedUrl):
  with openDb(migratedUrl) as conn:
    for start, end, breakStart, breakEnd in (("08:30", "17:30", None, None), ("09:00", "09:00", None, None), ("09:00", "18:00", "12:30", "13:30")):
      expectViolation(conn, psycopg.errors.CheckViolation,
                      "INSERT INTO shift_types (code, name, start_time, end_time, break_start, break_end) VALUES ('x', '某班', %s, %s, %s, %s)",
                      (start, end, breakStart, breakEnd))


def testBreakStartAndEndGoTogether(migratedUrl):
  with openDb(migratedUrl) as conn:
    expectViolation(conn, psycopg.errors.CheckViolation,
                    "INSERT INTO shift_types (code, name, start_time, end_time, break_start) VALUES ('x', '某班', '09:00', '18:00', '12:00')")


def testCrossMidnightShiftAllowed(migratedUrl):
  with openDb(migratedUrl) as conn:
    insertType(conn, "night", "22:00", "06:00", "02:00", "03:00")


def testRosterRulesAndCascade(migratedUrl):
  with openDb(migratedUrl) as conn:
    userId = insertActor(conn, "hr").userId
    employeeId = insertEmployee(conn)
    standard = conn.execute("SELECT id FROM shift_types WHERE code = 'standard'").fetchone()["id"]
    rosterId = conn.execute(
      "INSERT INTO shift_rosters (employee_id, effective_from, created_by, created_at) VALUES (%s, '2026-11-23', %s, now()) RETURNING id",
      (employeeId, userId),
    ).fetchone()["id"]
    conn.execute("INSERT INTO shift_roster_days (roster_id, weekday, shift_type_id) VALUES (%s, 0, %s)", (rosterId, standard))
    expectViolation(conn, psycopg.errors.CheckViolation,
                    "INSERT INTO shift_roster_days (roster_id, weekday, shift_type_id) VALUES (%s, 7, %s)", (rosterId, standard))
    expectViolation(conn, psycopg.errors.UniqueViolation,
                    "INSERT INTO shift_rosters (employee_id, effective_from, created_by, created_at) VALUES (%s, '2026-11-23', %s, now())",
                    (employeeId, userId))
    conn.execute("DELETE FROM shift_rosters WHERE id = %s", (rosterId,))
    assert conn.execute("SELECT count(*) AS n FROM shift_roster_days").fetchone()["n"] == 0


def testOneOverridePerEmployeeDay(migratedUrl):
  with openDb(migratedUrl) as conn:
    userId = insertActor(conn, "hr").userId
    employeeId = insertEmployee(conn)
    sql = (
      "INSERT INTO shift_overrides (employee_id, day, shift_type_id, created_by, created_at, updated_by, updated_at) "
      "VALUES (%s, '2026-11-24', NULL, %s, now(), %s, now())"
    )
    conn.execute(sql, (employeeId, userId, userId))
    expectViolation(conn, psycopg.errors.UniqueViolation, sql, (employeeId, userId, userId))
