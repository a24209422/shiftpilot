import threading
from datetime import datetime

from app.infra.db import openDb
from app.infra.errors import AppError
from app.modules.leave import requests
from tests.leave.world import makeWorld


def testConcurrentRequestsCannotTogetherExceedQuota(migratedUrl):
  w = makeWorld(migratedUrl)
  # 特休 56 小時：兩張各 40 小時（不同週），各自都沒超過，加起來超過
  weeks = [(datetime(2026, 11, 30, 9), datetime(2026, 12, 4, 18)), (datetime(2026, 12, 7, 9), datetime(2026, 12, 11, 18))]
  barrier = threading.Barrier(2)
  outcomes = [None, None]

  def attempt(index):
    barrier.wait()
    try:
      with openDb(migratedUrl) as conn:
        start, end = weeks[index]
        requests.createRequest(conn, w.aliceActor, requests.LeaveInput(w.types["annual"], start, end), datetime(2026, 11, 21, 10))
      outcomes[index] = "ok"
    except AppError as error:
      outcomes[index] = error.code

  threads = [threading.Thread(target=attempt, args=(index,)) for index in range(2)]
  for thread in threads:
    thread.start()
  for thread in threads:
    thread.join()
  assert sorted(outcomes) == ["LEAVE_QUOTA_EXCEEDED", "ok"], outcomes
