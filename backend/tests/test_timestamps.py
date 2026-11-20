from datetime import datetime, timedelta

from app.infra.db import openDb
from app.modules.booking import service as bookingService
from app.modules.booking.service import BookingInput
from app.modules.core import service as coreService
from tests.helpers import insertActor


def isNow(value) -> bool:
  # 資料庫容器的時區是 UTC，用資料庫的 now() 會和 Python 端的本地時間差上好幾個小時；
  # 全系統用同一個時間來源（Python 的本地時間），畫面上的建立時間才跟排程時間對得起來
  return abs(datetime.now() - value) < timedelta(minutes=2)


def testAuditUserAndBookingTimestampsUseApplicationClock(migratedUrl):
  with openDb(migratedUrl) as conn:
    admin = insertActor(conn, "admin", "admin@example.com")
    user = coreService.createUser(conn, admin, "a@x.com", "correct-horse", "employee")
    employeeId = conn.execute(
      "INSERT INTO departments (name) VALUES ('d') RETURNING id"
    ).fetchone()["id"]
    employeeId = conn.execute(
      "INSERT INTO employees (employee_no, name, department_id, job_title, hired_on) VALUES ('E1', 'n', %s, 't', '2025-01-01') RETURNING id",
      (employeeId,),
    ).fetchone()["id"]
    start = datetime(2026, 11, 24, 10)
    booking = bookingService.createBooking(
      conn, admin, BookingInput("會", "會議", start, start + timedelta(hours=1), [], [], organizerEmployeeId=employeeId)
    )
    auditAt = coreService.listAudit(conn, limit=1)[0]["at"]
    userCreatedAt = conn.execute("SELECT created_at FROM users WHERE id = %s", (user["id"],)).fetchone()["created_at"]
    bookingCreatedAt = conn.execute("SELECT created_at FROM bookings WHERE id = %s", (booking["id"],)).fetchone()["created_at"]
  assert isNow(datetime.fromisoformat(auditAt))
  assert isNow(userCreatedAt)
  assert isNow(bookingCreatedAt)
