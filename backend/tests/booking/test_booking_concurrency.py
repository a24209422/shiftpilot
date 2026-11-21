import threading
from datetime import date, datetime, time, timedelta

from app.infra.db import openDb
from app.infra.errors import AppError
from app.modules.booking import service
from app.modules.booking.service import BookingInput
from app.modules.org import service as orgService
from tests.helpers import insertActor


def testConcurrentBookingsOfSameResourceOnlyOneSucceeds(migratedUrl):
  with openDb(migratedUrl) as conn:
    admin = insertActor(conn, "admin", "admin@example.com")
    departmentId = orgService.createDepartment(conn, admin, "工程部")["id"]
    actors = []
    for number in ("E001", "E002"):
      employee = orgService.createEmployee(
        conn, admin, {"employeeNo": number, "name": number, "departmentId": departmentId, "jobTitle": "工程師", "hiredOn": date(2025, 1, 1)}
      )
      actors.append(insertActor(conn, "employee", f"{number}@example.com", employee["id"]))
    resourceIds = [service.createResource(conn, admin, {"name": f"會議室{n}", "kind": "room"})["id"] for n in range(10)]

  weekdays = [d for d in (date(2026, 12, 1) + timedelta(days=n) for n in range(20)) if d.weekday() < 5][:10]
  for roundNumber, resourceId in enumerate(resourceIds):
    # 每輪用不同的日期：同一批員工不能每輪都在同一個時段，否則會先被參加者警告擋住，測不到資源撞期
    # 還要避開週末：沒排班的人在休息日也會先被不在班的警告擋住
    day = weekdays[roundNumber]
    barrier = threading.Barrier(2)
    outcomes = [None, None]

    def attempt(index):
      barrier.wait()
      try:
        with openDb(migratedUrl) as conn:
          startAt = datetime.combine(day, time(10))
          data = BookingInput("搶會議室", "會議", startAt, startAt + timedelta(hours=1), [resourceId], [])
          service.createBooking(conn, actors[index], data)
        outcomes[index] = "ok"
      except AppError as error:
        outcomes[index] = error.code

    threads = [threading.Thread(target=attempt, args=(index,)) for index in range(2)]
    for thread in threads:
      thread.start()
    for thread in threads:
      thread.join()
    assert sorted(outcomes) == ["RESOURCE_CONFLICT", "ok"], outcomes
