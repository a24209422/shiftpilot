from datetime import datetime

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


def typeId(conn, code):
  return conn.execute("SELECT id FROM leave_types WHERE code = %s", (code,)).fetchone()["id"]


def insertRequest(conn, employeeId, userId, startAt, endAt, status="pending"):
  decided = status in ("approved", "rejected", "cancelled")
  cancelled = status in ("withdrawn", "cancelled")
  return conn.execute(
    "INSERT INTO leave_requests (employee_id, leave_type_id, start_at, end_at, hours, status, decided_by, decided_at, "
    "cancelled_by, cancelled_at, created_by, created_at) VALUES (%s, %s, %s, %s, 8, %s, %s, %s, %s, %s, %s, now()) RETURNING id",
    (
      employeeId, typeId(conn, "personal"), startAt, endAt, status,
      userId if decided else None, datetime(2026, 11, 20) if decided else None,
      userId if cancelled else None, datetime(2026, 11, 20) if cancelled else None, userId,
    ),
  ).fetchone()["id"]


def testMigrationSeedsNineLeaveTypes(migratedUrl):
  with openDb(migratedUrl) as conn:
    rows = conn.execute("SELECT code, quota_kind, annual_cap_hours FROM leave_types ORDER BY id").fetchall()
  assert [row["code"] for row in rows] == [
    "annual", "personal", "sick", "menstrual", "marriage", "paternity", "bereavement", "official", "maternity",
  ]
  assert rows[0]["quota_kind"] == "seniority" and rows[0]["annual_cap_hours"] is None
  assert rows[1]["quota_kind"] == "yearly_cap" and rows[1]["annual_cap_hours"] == 112


def testOnlyOneSeniorityType(migratedUrl):
  with openDb(migratedUrl) as conn, pytest.raises(psycopg.errors.UniqueViolation):
    conn.execute("INSERT INTO leave_types (code, name, paid_ratio, quota_kind) VALUES ('annual2', '特休二', 1, 'seniority')")


def testYearlyCapRequiresCapHours(migratedUrl):
  with openDb(migratedUrl) as conn, pytest.raises(psycopg.errors.CheckViolation):
    conn.execute("INSERT INTO leave_types (code, name, paid_ratio, quota_kind) VALUES ('x', '某假', 1, 'yearly_cap')")


def testCapHoursOnlyForYearlyCap(migratedUrl):
  with openDb(migratedUrl) as conn, pytest.raises(psycopg.errors.CheckViolation):
    conn.execute("INSERT INTO leave_types (code, name, paid_ratio, quota_kind, annual_cap_hours) VALUES ('x', '某假', 1, 'none', 8)")


def testOverlappingActiveRequestsRejectedByDatabase(migratedUrl):
  with openDb(migratedUrl) as conn:
    userId = insertActor(conn, "hr").userId
    employeeId = insertEmployee(conn)
    insertRequest(conn, employeeId, userId, datetime(2026, 11, 24, 9), datetime(2026, 11, 24, 18))
    with pytest.raises(psycopg.errors.ExclusionViolation):
      insertRequest(conn, employeeId, userId, datetime(2026, 11, 24, 13), datetime(2026, 11, 24, 15), "approved")


def testWithdrawnRequestDoesNotBlockNewOne(migratedUrl):
  with openDb(migratedUrl) as conn:
    userId = insertActor(conn, "hr").userId
    employeeId = insertEmployee(conn)
    insertRequest(conn, employeeId, userId, datetime(2026, 11, 24, 9), datetime(2026, 11, 24, 18), "withdrawn")
    insertRequest(conn, employeeId, userId, datetime(2026, 11, 24, 9), datetime(2026, 11, 24, 18))


def testDecisionColumnsMatchStatus(migratedUrl):
  with openDb(migratedUrl) as conn:
    userId = insertActor(conn, "hr").userId
    employeeId = insertEmployee(conn)
    with pytest.raises(psycopg.errors.CheckViolation):
      conn.execute(
        "INSERT INTO leave_requests (employee_id, leave_type_id, start_at, end_at, hours, status, created_by, created_at) "
        "VALUES (%s, %s, '2026-11-24 09:00', '2026-11-24 18:00', 8, 'approved', %s, now())",
        (employeeId, typeId(conn, "personal"), userId),
      )


def testAdjustmentNeedsNonZeroHoursAndReason(migratedUrl):
  with openDb(migratedUrl) as conn:
    userId = insertActor(conn, "hr").userId
    employeeId = insertEmployee(conn)
    for hours, reason in ((0, "更正"), (8, "  ")):
      with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
        conn.execute(
          "INSERT INTO leave_adjustments (employee_id, leave_type_id, period_start, hours, reason, created_by, created_at) "
          "VALUES (%s, %s, '2026-01-01', %s, %s, %s, now())",
          (employeeId, typeId(conn, "personal"), hours, reason, userId),
        )
