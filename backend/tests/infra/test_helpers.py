from datetime import date, datetime

import pytest

from app.infra.actor import Actor
from app.infra.errors import AppError
from app.infra.serialize import camelizeRow, parseLocalTime


def testCamelizeRowConvertsKeysAndDatetimes():
  row = {"start_at": datetime(2026, 11, 24, 10, 0), "booking_id": 1, "items": [{"employee_id": 2}]}
  assert camelizeRow(row) == {"startAt": "2026-11-24T10:00:00", "bookingId": 1, "items": [{"employeeId": 2}]}


def testCamelizeRowConvertsDatesAndLeavesOtherValues():
  assert camelizeRow({"hired_on": date(2026, 1, 5), "name": "王", "n": None}) == {"hiredOn": "2026-01-05", "name": "王", "n": None}


def testParseLocalTimeAcceptsMinuteAndSecondForms():
  assert parseLocalTime("2026-11-24T10:00") == datetime(2026, 11, 24, 10, 0)
  assert parseLocalTime("2026-11-24T10:00:30") == datetime(2026, 11, 24, 10, 0, 30)


@pytest.mark.parametrize("text", ["2026-11-24T10:00+08:00", "2026-11-24T10:00Z", "2026/11/24 10:00", "2026-13-45T10:00"])
def testParseLocalTimeRejectsOffsetsAndBadFormats(text):
  with pytest.raises(AppError) as info:
    parseLocalTime(text)
  assert info.value.code == "VALIDATION"
  assert info.value.status == 422


def testAppErrorKeepsFields():
  error = AppError("NOT_FOUND", "找不到", 404, {"id": 1})
  assert (error.code, error.message, error.status, error.details) == ("NOT_FOUND", "找不到", 404, {"id": 1})
  assert AppError("X", "y", 400).details is None


def testActorIsFrozen():
  actor = Actor(userId=1, role="admin", employeeId=None)
  with pytest.raises(Exception):
    actor.role = "employee"
