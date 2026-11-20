from datetime import date, datetime

import psycopg
import pytest

from app.infra.actor import Actor
from app.infra.db import openDb
from app.modules.core.service import listAudit, writeAudit


def insertUser(conn, email="a@x.com", role="employee", employeeId=None):
  return conn.execute(
    "INSERT INTO users (email, password_hash, role, employee_id) VALUES (%s, 'hash', %s, %s) RETURNING id",
    (email, role, employeeId),
  ).fetchone()["id"]


def insertEmployee(conn, employeeNo="E001"):
  departmentId = conn.execute("INSERT INTO departments (name) VALUES (%s) RETURNING id", (f"部門{employeeNo}",)).fetchone()["id"]
  return conn.execute(
    "INSERT INTO employees (employee_no, name, department_id, job_title, hired_on) VALUES (%s, '王', %s, '工程師', '2025-01-01') RETURNING id",
    (employeeNo, departmentId),
  ).fetchone()["id"]


def testAuditLogRejectsUpdateAndDelete(migratedUrl):
  with openDb(migratedUrl) as conn:
    writeAudit(conn, None, "core", "createUser", "user", 1, None, {"email": "a@x.com"})
  with pytest.raises(psycopg.errors.InsufficientPrivilege):
    with openDb(migratedUrl) as conn:
      conn.execute("UPDATE audit_log SET action = 'x'")
  with pytest.raises(psycopg.errors.InsufficientPrivilege):
    with openDb(migratedUrl) as conn:
      conn.execute("DELETE FROM audit_log")


def testWriteAuditStoresBeforeAndAfter(migratedUrl):
  with openDb(migratedUrl) as conn:
    userId = insertUser(conn)
    actor = Actor(userId=userId, role="admin", employeeId=None)
    auditId = writeAudit(conn, actor, "booking", "updateBooking", "booking", 5, {"title": "舊"}, {"title": "新", "day": date(2026, 11, 24)})
    row = listAudit(conn)[0]
  assert row["id"] == auditId
  assert row["before"] == {"title": "舊"}
  assert row["after"] == {"title": "新", "day": "2026-11-24"}
  assert (row["userId"], row["module"], row["action"], row["entity"], row["entityId"]) == (userId, "booking", "updateBooking", "booking", "5")
  assert isinstance(datetime.fromisoformat(row["at"]), datetime)


def testWriteAuditAllowsNoActor(migratedUrl):
  with openDb(migratedUrl) as conn:
    writeAudit(conn, None, "core", "createUser", "user", 1, None, None)
    row = listAudit(conn)[0]
  assert row["userId"] is None and row["before"] is None and row["after"] is None


def testListAuditNewestFirstAndPagesByBeforeId(migratedUrl):
  with openDb(migratedUrl) as conn:
    ids = [writeAudit(conn, None, "org" if n % 2 else "booking", "act", "e", n, None, None) for n in range(5)]
    assert [row["id"] for row in listAudit(conn, limit=2)] == [ids[4], ids[3]]
    assert [row["id"] for row in listAudit(conn, limit=2, beforeId=ids[3])] == [ids[2], ids[1]]
    assert {row["module"] for row in listAudit(conn, module="org")} == {"org"}


def testUserEmailIsUniqueIgnoringCase(migratedUrl):
  with pytest.raises(psycopg.errors.UniqueViolation):
    with openDb(migratedUrl) as conn:
      insertUser(conn, "A@x.com")
      insertUser(conn, "a@X.com")


def testUserEmployeeIdIsUnique(migratedUrl):
  with pytest.raises(psycopg.errors.UniqueViolation):
    with openDb(migratedUrl) as conn:
      employeeId = insertEmployee(conn)
      insertUser(conn, "a@x.com", employeeId=employeeId)
      insertUser(conn, "b@x.com", employeeId=employeeId)


def testRoleCheckRejectsUnknownRole(migratedUrl):
  with pytest.raises(psycopg.errors.CheckViolation):
    with openDb(migratedUrl) as conn:
      insertUser(conn, role="superuser")


def testSessionsForeignKeyCascadesOnUserDelete(migratedUrl):
  # 不能真的刪使用者來測：audit_log 對 users 有外鍵，刪除時資料庫要對 audit_log 做 FOR KEY SHARE 檢查，
  # 而 UPDATE 權限已撤銷，會變成 permission denied。使用者本來就只停用不刪除，所以改查外鍵定義
  with openDb(migratedUrl) as conn:
    row = conn.execute(
      "SELECT confdeltype FROM pg_constraint WHERE conrelid = 'sessions'::regclass AND contype = 'f' "
      "AND confrelid = 'users'::regclass"
    ).fetchone()
  assert row["confdeltype"] == "c"
