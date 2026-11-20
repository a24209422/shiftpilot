from datetime import date
from types import SimpleNamespace

from app.infra.db import openDb
from app.modules.org import service as orgService
from tests.helpers import insertActor


def makeWorld(url):
  """boss 是 alice 的直屬主管；bob 沒有主管；carol 是人資。全部 2025-01-01 到職，2026 年的特休是 56 小時。"""
  w = SimpleNamespace(url=url)
  with openDb(url) as conn:
    setup = insertActor(conn, "admin", "setup@example.com")
    departmentId = orgService.createDepartment(conn, setup, "工程部")["id"]

    def employee(number, name, managerId=None):
      return orgService.createEmployee(conn, setup, {
        "employeeNo": number, "name": name, "departmentId": departmentId, "jobTitle": "工程師",
        "hiredOn": date(2025, 1, 1), "managerId": managerId,
      })["id"]

    w.boss = employee("E001", "boss")
    w.alice = employee("E002", "alice", w.boss)
    w.bob = employee("E003", "bob")
    w.carol = employee("E004", "carol")
    w.bossActor = insertActor(conn, "manager", "boss@example.com", w.boss)
    w.aliceActor = insertActor(conn, "employee", "alice@example.com", w.alice)
    w.bobActor = insertActor(conn, "employee", "bob@example.com", w.bob)
    w.hrActor = insertActor(conn, "hr", "carol@example.com", w.carol)
    w.adminActor = setup
    w.types = {row["code"]: row["id"] for row in conn.execute("SELECT id, code FROM leave_types").fetchall()}
  return w
