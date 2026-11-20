from datetime import datetime, timedelta

import pytest

from app.infra.actor import Actor
from app.infra.db import openDb
from app.infra.errors import AppError
from app.modules.core import service

start = datetime(2026, 11, 24, 9, 0)
password = "correct-horse"


def makeUser(conn, email="admin@x.com", role="employee", userPassword=password, employeeId=None):
  return service.createUser(conn, None, email, userPassword, role, employeeId)


def expectError(code, call, *args, **kwargs):
  with pytest.raises(AppError) as info:
    call(*args, **kwargs)
  assert info.value.code == code
  return info.value


def testAuthenticateIgnoresEmailCaseAndWhitespace(migratedUrl):
  with openDb(migratedUrl) as conn:
    created = makeUser(conn, "admin@x.com")
    user = service.authenticate(conn, "  Admin@X.com ", password, start)
  assert user["id"] == created["id"] and user["role"] == "employee" and "passwordHash" not in user


def testWrongPasswordAndUnknownEmailGiveSameError(migratedUrl):
  with openDb(migratedUrl) as conn:
    makeUser(conn)
    wrong = expectError("INVALID_CREDENTIALS", service.authenticate, conn, "admin@x.com", "wrong-password", start)
    unknown = expectError("INVALID_CREDENTIALS", service.authenticate, conn, "nobody@x.com", password, start)
  assert (wrong.message, wrong.status) == (unknown.message, unknown.status) == ("帳號或密碼錯誤", 401)


def testLockAfterFiveFailures(migratedUrl):
  with openDb(migratedUrl) as conn:
    makeUser(conn)
    for _ in range(5):
      expectError("INVALID_CREDENTIALS", service.authenticate, conn, "admin@x.com", "wrong-password", start)
    locked = expectError("TOO_MANY_ATTEMPTS", service.authenticate, conn, "admin@x.com", password, start)
    assert locked.status == 429
    assert service.authenticate(conn, "admin@x.com", password, start + timedelta(minutes=16))["email"] == "admin@x.com"


def testFailuresArePersistedEvenThoughTheRequestFails(migratedUrl):
  # 登入失敗會丟錯誤，HTTP 層遇到錯誤會 rollback；失敗次數要先 commit 才不會被一起吃掉
  with openDb(migratedUrl) as conn:
    makeUser(conn)
  for _ in range(5):
    with pytest.raises(AppError):
      with openDb(migratedUrl) as conn:
        service.authenticate(conn, "admin@x.com", "wrong-password", start)
  with openDb(migratedUrl) as conn:
    expectError("TOO_MANY_ATTEMPTS", service.authenticate, conn, "admin@x.com", password, start)


def testSuccessResetsFailureCount(migratedUrl):
  with openDb(migratedUrl) as conn:
    makeUser(conn)
    for _ in range(3):
      expectError("INVALID_CREDENTIALS", service.authenticate, conn, "admin@x.com", "wrong-password", start)
    service.authenticate(conn, "admin@x.com", password, start)
    for _ in range(4):
      expectError("INVALID_CREDENTIALS", service.authenticate, conn, "admin@x.com", "wrong-password", start)
    assert service.authenticate(conn, "admin@x.com", password, start)["email"] == "admin@x.com"


def testDeactivatedUserCannotAuthenticate(migratedUrl):
  with openDb(migratedUrl) as conn:
    user = makeUser(conn)
    conn.execute("UPDATE users SET is_active = false WHERE id = %s", (user["id"],))
    expectError("INVALID_CREDENTIALS", service.authenticate, conn, "admin@x.com", password, start)


def testSessionRoundTrip(migratedUrl):
  with openDb(migratedUrl) as conn:
    user = makeUser(conn, role="hr")
    token = service.createSession(conn, user["id"], now=start)
    assert service.getSessionActor(conn, token, start) == Actor(userId=user["id"], role="hr", employeeId=None)
    stored = conn.execute("SELECT id_hash FROM sessions").fetchone()["id_hash"]
    assert stored != token
    service.deleteSession(conn, token)
    assert service.getSessionActor(conn, token, start) is None
    assert service.getSessionActor(conn, "no-such-token", start) is None


def testExpiredSessionReturnsNone(migratedUrl):
  with openDb(migratedUrl) as conn:
    user = makeUser(conn)
    token = service.createSession(conn, user["id"], now=start)
    assert service.getSessionActor(conn, token, start + timedelta(hours=11)) is not None
    assert service.getSessionActor(conn, token, start + timedelta(hours=13)) is None


def testDeactivatedUserSessionReturnsNone(migratedUrl):
  with openDb(migratedUrl) as conn:
    user = makeUser(conn)
    token = service.createSession(conn, user["id"], now=start)
    conn.execute("UPDATE users SET is_active = false WHERE id = %s", (user["id"],))
    assert service.getSessionActor(conn, token, start) is None


def makeAdminActor(conn):
  admin = makeUser(conn, "boss@x.com", "admin")
  return Actor(userId=admin["id"], role="admin", employeeId=None)


def testDeactivatingUserDeletesSessions(migratedUrl):
  with openDb(migratedUrl) as conn:
    admin = makeAdminActor(conn)
    user = makeUser(conn)
    service.createSession(conn, user["id"], now=start)
    service.updateUser(conn, admin, user["id"], {"isActive": False})
    assert conn.execute("SELECT count(*) AS n FROM sessions").fetchone()["n"] == 0


def testChangePasswordRequiresCurrentAndDropsSessions(migratedUrl):
  with openDb(migratedUrl) as conn:
    user = makeUser(conn)
    actor = Actor(userId=user["id"], role="employee", employeeId=None)
    service.createSession(conn, user["id"], now=start)
    expectError("VALIDATION", service.changePassword, conn, actor, "not-the-password", "new-password-1")
    service.changePassword(conn, actor, password, "new-password-1")
    assert conn.execute("SELECT count(*) AS n FROM sessions").fetchone()["n"] == 0
    expectError("INVALID_CREDENTIALS", service.authenticate, conn, "admin@x.com", password, start)
    assert service.authenticate(conn, "admin@x.com", "new-password-1", start)["id"] == user["id"]


def testResetPasswordUnlocksAccount(migratedUrl):
  with openDb(migratedUrl) as conn:
    admin = makeAdminActor(conn)
    user = makeUser(conn)
    for _ in range(5):
      expectError("INVALID_CREDENTIALS", service.authenticate, conn, "admin@x.com", "wrong-password", start)
    service.createSession(conn, user["id"], now=start)
    service.resetPassword(conn, admin, user["id"], "brand-new-pass")
    assert conn.execute("SELECT count(*) AS n FROM sessions").fetchone()["n"] == 0
    assert service.authenticate(conn, "admin@x.com", "brand-new-pass", start)["id"] == user["id"]
    expectError("NOT_FOUND", service.resetPassword, conn, admin, 9999, "brand-new-pass")


def testPasswordLengthLimits(migratedUrl):
  with openDb(migratedUrl) as conn:
    expectError("VALIDATION", service.createUser, conn, None, "a@x.com", "1234567", "employee")
    expectError("VALIDATION", service.createUser, conn, None, "b@x.com", "x" * 129, "employee")
    assert service.createUser(conn, None, "c@x.com", "密碼密碼密碼密碼", "employee")["email"] == "c@x.com"
    assert service.createUser(conn, None, "d@x.com", "x" * 128, "employee")["email"] == "d@x.com"


def testCreateUserValidatesRoleAndEmail(migratedUrl):
  with openDb(migratedUrl) as conn:
    expectError("VALIDATION", service.createUser, conn, None, "a@x.com", password, "superuser")
    expectError("VALIDATION", service.createUser, conn, None, "   ", password, "employee")
    makeUser(conn, " Same@X.com ")
    assert service.listUsers(conn)[0]["email"] == "Same@X.com"
    expectError("DUPLICATE", service.createUser, conn, None, "same@x.COM", password, "employee")


def testCannotModifySelfRoleOrActive(migratedUrl):
  with openDb(migratedUrl) as conn:
    admin = makeAdminActor(conn)
    expectError("CANNOT_MODIFY_SELF", service.updateUser, conn, admin, admin.userId, {"role": "employee"})
    expectError("CANNOT_MODIFY_SELF", service.updateUser, conn, admin, admin.userId, {"isActive": False})
    assert service.getUser(conn, admin.userId)["isActive"] is True
    other = makeUser(conn)
    assert service.updateUser(conn, admin, other["id"], {"role": "hr"})["role"] == "hr"


def testListUsersNeverIncludesHash(migratedUrl):
  with openDb(migratedUrl) as conn:
    makeUser(conn)
    users = service.listUsers(conn)
  assert len(users) == 1 and not any("hash" in key.lower() or "password" in key.lower() for key in users[0])


def testAuditNeverContainsPassword(migratedUrl):
  with openDb(migratedUrl) as conn:
    admin = makeAdminActor(conn)
    user = service.createUser(conn, admin, "w@x.com", "first-secret-pw", "employee")
    service.updateUser(conn, admin, user["id"], {"role": "manager"})
    service.resetPassword(conn, admin, user["id"], "second-secret-pw")
    service.changePassword(conn, Actor(userId=user["id"], role="manager", employeeId=None), "second-secret-pw", "third-secret-pw")
    dump = str(service.listAudit(conn, module="core"))
  assert "createUser" in dump and "resetPassword" in dump
  for secret in ("first-secret-pw", "second-secret-pw", "third-secret-pw", "$argon2"):
    assert secret not in dump


def makeLinkedUser(conn):
  from datetime import date

  from app.modules.org import service as orgService

  departmentId = orgService.createDepartment(conn, None, "工程部")["id"]
  employeeId = orgService.createEmployee(
    conn, None, {"employeeNo": "E001", "name": "王小明", "departmentId": departmentId, "jobTitle": "工程師", "hiredOn": date(2025, 1, 1)}
  )["id"]
  return employeeId, makeUser(conn, "emp@x.com", employeeId=employeeId)


def testDeactivatedEmployeeCannotLoginAndSessionsStopWorking(migratedUrl):
  from app.modules.org import service as orgService

  with openDb(migratedUrl) as conn:
    employeeId, user = makeLinkedUser(conn)
    token = service.createSession(conn, user["id"], now=start)
    assert service.getSessionActor(conn, token, start) is not None
    orgService.updateEmployee(conn, None, employeeId, {"isActive": False})
    assert service.getSessionActor(conn, token, start) is None
    expectError("INVALID_CREDENTIALS", service.authenticate, conn, "emp@x.com", password, start)
    orgService.updateEmployee(conn, None, employeeId, {"isActive": True})
    assert service.getSessionActor(conn, token, start) is not None
    assert service.authenticate(conn, "emp@x.com", password, start)["id"] == user["id"]
