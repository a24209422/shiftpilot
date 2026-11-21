from datetime import date, timedelta

import pytest

from app import cli
from app.infra.db import openDb
from app.infra.errors import AppError
from app.modules.core import service as coreService
from app.modules.core.service import listAudit
from app.modules.org import service as orgService


def countRows(url, table):
  with openDb(url) as conn:
    return conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]


def testMigrateCommandAppliesThenNoop(databaseUrl):
  assert cli.migrateCommand(databaseUrl) == ["org/0001_org.sql", "core/0001_core.sql", "booking/0001_booking.sql", "shift/0001_shift.sql", "leave/0001_leave.sql"]
  assert cli.migrateCommand(databaseUrl) == []


def testCreateUserCommandCreatesAdminWhoCanAuthenticate(migratedUrl):
  userId = cli.createUserCommand(migratedUrl, "admin@example.com", "admin", "correct-horse")
  with openDb(migratedUrl) as conn:
    user = coreService.authenticate(conn, "admin@example.com", "correct-horse")
    audit = [row for row in listAudit(conn, module="core") if row["action"] == "createUser"]
  assert user["id"] == userId and user["role"] == "admin" and user["employeeId"] is None
  assert len(audit) == 1 and audit[0]["userId"] is None


def testCreateUserCommandLinksEmployeeNo(migratedUrl):
  with openDb(migratedUrl) as conn:
    departmentId = orgService.createDepartment(conn, None, "工程部")["id"]
    employeeId = orgService.createEmployee(
      conn, None, {"employeeNo": "E001", "name": "王小明", "departmentId": departmentId, "jobTitle": "工程師", "hiredOn": date(2025, 1, 1)}
    )["id"]
  userId = cli.createUserCommand(migratedUrl, "emp@example.com", "employee", "correct-horse", "E001")
  with openDb(migratedUrl) as conn:
    assert coreService.getUser(conn, userId)["employeeId"] == employeeId
  with pytest.raises(AppError) as info:
    cli.createUserCommand(migratedUrl, "other@example.com", "employee", "correct-horse", "NOPE")
  assert info.value.code == "NOT_FOUND"
  assert countRows(migratedUrl, "users") == 1


def testSeedDemoPopulatesAndRefusesSecondRun(migratedUrl):
  cli.createUserCommand(migratedUrl, "admin@example.com", "admin", "correct-horse")
  cli.seedDemoCommand(migratedUrl)
  assert countRows(migratedUrl, "departments") == 3
  assert countRows(migratedUrl, "employees") == 4
  assert countRows(migratedUrl, "resources") == 4
  assert countRows(migratedUrl, "bookings") >= 5
  with openDb(migratedUrl) as conn:
    kinds = sorted(row["kind"] for row in conn.execute("SELECT kind FROM resources").fetchall())
    managedChain = conn.execute("SELECT count(*) AS n FROM employees WHERE manager_id IS NOT NULL").fetchone()["n"]
  assert kinds == ["equipment", "room", "room", "vehicle"] and managedChain >= 3
  with pytest.raises(AppError) as info:
    cli.seedDemoCommand(migratedUrl)
  assert (info.value.code, info.value.status) == ("NOT_EMPTY", 409)
  assert countRows(migratedUrl, "employees") == 4


def testSeedDemoCreatesNoUsers(migratedUrl):
  cli.createUserCommand(migratedUrl, "admin@example.com", "admin", "correct-horse")
  cli.seedDemoCommand(migratedUrl)
  assert countRows(migratedUrl, "users") == 1


def testSeedDemoNeedsAnAdminBecauseBookingsNeedACreator(migratedUrl):
  with pytest.raises(AppError) as info:
    cli.seedDemoCommand(migratedUrl)
  assert info.value.code == "NO_ADMIN"
  assert countRows(migratedUrl, "employees") == 0


def testSeedDemoBookingsFillsComingWeekAndSkipsConflicts(migratedUrl):
  cli.createUserCommand(migratedUrl, "admin@example.com", "admin", "correct-horse")
  cli.seedDemoCommand(migratedUrl)
  before = countRows(migratedUrl, "bookings")
  created, skipped = cli.seedDemoBookingsCommand(migratedUrl)
  assert created > 0
  assert countRows(migratedUrl, "bookings") == before + created
  with openDb(migratedUrl) as conn:
    days = {row["day"] for row in conn.execute("SELECT DISTINCT start_at::date AS day FROM bookings WHERE created_at IS NOT NULL").fetchall()}
    audits = [row for row in listAudit(conn, module="booking", limit=500) if row["action"] == "createBooking"]
  assert {date.today() + timedelta(days=offset) for offset in range(7)} <= days
  assert len(audits) == before + created
  # 第二次執行時每一筆都會撞到第一次寫入的，全部略過，不會重複新增
  assert cli.seedDemoBookingsCommand(migratedUrl) == (0, created + skipped)
  assert countRows(migratedUrl, "bookings") == before + created


def testSeedDemoBookingsNeedsEmployees(migratedUrl):
  cli.createUserCommand(migratedUrl, "admin@example.com", "admin", "correct-horse")
  with pytest.raises(AppError) as info:
    cli.seedDemoBookingsCommand(migratedUrl)
  assert info.value.code == "NO_EMPLOYEES"
  assert countRows(migratedUrl, "bookings") == 0


def testMainRejectsPasswordOnCommandLine(capsys):
  with pytest.raises(SystemExit) as info:
    cli.main(["createUser", "--email", "a@x.com", "--role", "admin", "--password", "secret-pass"])
  assert info.value.code == 2


def testMainCreateUserAsksPasswordTwice(migratedUrl, monkeypatch, capsys):
  monkeypatch.setenv("DATABASE_URL", migratedUrl)
  answers = iter(["correct-horse", "different-one"])
  monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(answers))
  assert cli.main(["createUser", "--email", "a@x.com", "--role", "admin"]) == 1
  assert countRows(migratedUrl, "users") == 0
  answers = iter(["correct-horse", "correct-horse"])
  assert cli.main(["createUser", "--email", "a@x.com", "--role", "admin"]) == 0
  assert countRows(migratedUrl, "users") == 1
  assert "correct-horse" not in capsys.readouterr().out
