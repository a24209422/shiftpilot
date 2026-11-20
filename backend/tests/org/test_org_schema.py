from datetime import date

import psycopg
import pytest

from app.infra.db import openDb


def insertDepartment(conn, name="工程部"):
  return conn.execute("INSERT INTO departments (name) VALUES (%s) RETURNING id", (name,)).fetchone()["id"]


def insertEmployee(conn, departmentId, employeeNo="E001", **extra):
  values = {"employee_no": employeeNo, "name": "王小明", "department_id": departmentId, "job_title": "工程師", "hired_on": date(2025, 1, 1)}
  values.update(extra)
  columns = ", ".join(values)
  placeholders = ", ".join(["%s"] * len(values))
  return conn.execute(f"INSERT INTO employees ({columns}) VALUES ({placeholders}) RETURNING id", list(values.values())).fetchone()["id"]


def testDepartmentCannotBeItsOwnParent(migratedUrl):
  with pytest.raises(psycopg.errors.CheckViolation):
    with openDb(migratedUrl) as conn:
      departmentId = insertDepartment(conn)
      conn.execute("UPDATE departments SET parent_id = id WHERE id = %s", (departmentId,))


def testEmployeeCannotBeOwnManager(migratedUrl):
  with pytest.raises(psycopg.errors.CheckViolation):
    with openDb(migratedUrl) as conn:
      employeeId = insertEmployee(conn, insertDepartment(conn))
      conn.execute("UPDATE employees SET manager_id = id WHERE id = %s", (employeeId,))


def testEmployeeNoMustBeUnique(migratedUrl):
  with pytest.raises(psycopg.errors.UniqueViolation):
    with openDb(migratedUrl) as conn:
      departmentId = insertDepartment(conn)
      insertEmployee(conn, departmentId, "E001")
      insertEmployee(conn, departmentId, "E001")


def testLeftOnCannotBeBeforeHiredOn(migratedUrl):
  with pytest.raises(psycopg.errors.CheckViolation):
    with openDb(migratedUrl) as conn:
      insertEmployee(conn, insertDepartment(conn), hired_on=date(2025, 6, 1), left_on=date(2025, 5, 31))


def testCalendarDayKindIsRestricted(migratedUrl):
  with pytest.raises(psycopg.errors.CheckViolation):
    with openDb(migratedUrl) as conn:
      conn.execute("INSERT INTO calendar_days (day, kind, name) VALUES ('2026-11-21', 'weekend', '週末')")


def testCalendarDayAcceptsHolidayAndMakeupWorkday(migratedUrl):
  with openDb(migratedUrl) as conn:
    conn.execute("INSERT INTO calendar_days (day, kind, name) VALUES ('2026-10-10', 'holiday', '國慶日')")
    conn.execute("INSERT INTO calendar_days (day, kind, name) VALUES ('2026-10-17', 'makeup_workday', '補班')")
    assert conn.execute("SELECT count(*) AS n FROM calendar_days").fetchone()["n"] == 2


def testEmployeeDefaultsToActive(migratedUrl):
  with openDb(migratedUrl) as conn:
    employeeId = insertEmployee(conn, insertDepartment(conn))
    row = conn.execute("SELECT is_active, left_on FROM employees WHERE id = %s", (employeeId,)).fetchone()
  assert row == {"is_active": True, "left_on": None}
