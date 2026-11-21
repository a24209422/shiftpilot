from datetime import date, datetime
from types import SimpleNamespace

from app.infra.db import openDb
from app.modules.org import service as orgService
from app.modules.shift import service
from tests.helpers import insertActor


def makeWorld(url):
  """boss 是 alice 的直屬主管；bob 沒有主管；carol 是人資；全部 2025-01-01 到職。
  evening 是 14:00–23:00、休息 18:00–19:00；night 是 22:00–06:00、休息 02:00–03:00 的跨日班。"""
  w = SimpleNamespace(url=url)
  with openDb(url) as conn:
    setup = insertActor(conn, "admin", "setup@example.com")
    departmentId = orgService.createDepartment(conn, setup, "客服部")["id"]

    def employee(number, name, managerId=None):
      return orgService.createEmployee(conn, setup, {
        "employeeNo": number, "name": name, "departmentId": departmentId, "jobTitle": "客服",
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
    w.standard = conn.execute("SELECT id FROM shift_types WHERE code = 'standard'").fetchone()["id"]
    w.evening = service.createShiftType(conn, setup, {
      "code": "evening", "name": "晚班", "startTime": "14:00", "endTime": "23:00", "breakStart": "18:00", "breakEnd": "19:00",
    })["id"]
    w.night = service.createShiftType(conn, setup, {
      "code": "night", "name": "大夜班", "startTime": "22:00", "endTime": "06:00", "breakStart": "02:00", "breakEnd": "03:00",
    })["id"]
  return w


def insertRoster(conn, w, employeeId, effectiveFrom, days):
  # 讀取側的測試直接寫資料表，不經過 Task 4 的寫入函式
  rosterId = conn.execute(
    "INSERT INTO shift_rosters (employee_id, effective_from, created_by, created_at) VALUES (%s, %s, %s, %s) RETURNING id",
    (employeeId, effectiveFrom, w.hrActor.userId, datetime(2026, 11, 20)),
  ).fetchone()["id"]
  for weekday, shiftTypeId in days.items():
    conn.execute("INSERT INTO shift_roster_days (roster_id, weekday, shift_type_id) VALUES (%s, %s, %s)", (rosterId, weekday, shiftTypeId))
  return rosterId


def insertOverride(conn, w, employeeId, day, shiftTypeId, note=""):
  conn.execute(
    "INSERT INTO shift_overrides (employee_id, day, shift_type_id, note, created_by, created_at, updated_by, updated_at) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
    (employeeId, day, shiftTypeId, note, w.hrActor.userId, datetime(2026, 11, 20), w.hrActor.userId, datetime(2026, 11, 20)),
  )
