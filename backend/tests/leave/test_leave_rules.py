from datetime import date, datetime

import pytest

from app.infra.errors import AppError
from app.modules.leave import rules
from app.modules.leave.rules import Period


def expectError(code, call, *args):
  with pytest.raises(AppError) as info:
    call(*args)
  assert info.value.code == code
  return info.value


@pytest.mark.parametrize(("day", "months", "expected"), [
  (date(2024, 1, 15), 6, date(2024, 7, 15)),
  (date(2025, 8, 31), 6, date(2026, 2, 28)),
  (date(2024, 2, 29), 12, date(2025, 2, 28)),
  (date(2024, 2, 29), 48, date(2028, 2, 29)),
  (date(2025, 11, 30), 3, date(2026, 2, 28)),
])
def testAddMonths(day, months, expected):
  assert rules.addMonths(day, months) == expected


# 2025-01-01 到職：勞基法第 38 條每個級距的邊界
@pytest.mark.parametrize(("day", "expected"), [
  (date(2025, 6, 30), None),
  (date(2025, 7, 1), Period(date(2025, 7, 1), date(2025, 12, 31), 24)),
  (date(2025, 12, 31), Period(date(2025, 7, 1), date(2025, 12, 31), 24)),
  (date(2026, 1, 1), Period(date(2026, 1, 1), date(2026, 12, 31), 56)),
  (date(2027, 1, 1), Period(date(2027, 1, 1), date(2027, 12, 31), 80)),
  (date(2028, 1, 1), Period(date(2028, 1, 1), date(2028, 12, 31), 112)),
  (date(2029, 6, 1), Period(date(2029, 1, 1), date(2029, 12, 31), 112)),
  (date(2030, 1, 1), Period(date(2030, 1, 1), date(2030, 12, 31), 120)),
  (date(2034, 12, 31), Period(date(2034, 1, 1), date(2034, 12, 31), 120)),
  (date(2035, 1, 1), Period(date(2035, 1, 1), date(2035, 12, 31), 128)),
  (date(2049, 1, 1), Period(date(2049, 1, 1), date(2049, 12, 31), 240)),
  (date(2055, 1, 1), Period(date(2055, 1, 1), date(2055, 12, 31), 240)),
])
def testSeniorityPeriodFollowsLaborStandardsAct(day, expected):
  assert rules.seniorityPeriod(date(2025, 1, 1), day) == expected


def testSeniorityPeriodForMonthEndHire():
  hiredOn = date(2025, 8, 31)
  assert rules.seniorityPeriod(hiredOn, date(2026, 2, 27)) is None
  assert rules.seniorityPeriod(hiredOn, date(2026, 2, 28)) == Period(date(2026, 2, 28), date(2026, 8, 30), 24)
  assert rules.seniorityPeriod(hiredOn, date(2026, 8, 31)) == Period(date(2026, 8, 31), date(2027, 8, 30), 56)


def testLeapDayHireAnniversary():
  assert rules.seniorityPeriod(date(2024, 2, 29), date(2025, 2, 28)) == Period(date(2025, 2, 28), date(2026, 2, 27), 56)


def testPeriodForOtherKindsIsCalendarYear():
  assert rules.periodFor("yearly_cap", 112, date(2025, 1, 1), date(2026, 5, 3)) == Period(date(2026, 1, 1), date(2026, 12, 31), 112)
  assert rules.periodFor("none", None, date(2025, 1, 1), date(2026, 5, 3)) == Period(date(2026, 1, 1), date(2026, 12, 31), None)
  assert rules.periodFor("seniority", None, date(2025, 1, 1), date(2025, 3, 1)) is None


def standardWindows(day):
  return [(datetime(2026, 11, day, 9), datetime(2026, 11, day, 12)), (datetime(2026, 11, day, 13), datetime(2026, 11, day, 18))]


nightWindows = [(datetime(2026, 11, 23, 22), datetime(2026, 11, 24, 2)), (datetime(2026, 11, 24, 3), datetime(2026, 11, 24, 6))]


@pytest.mark.parametrize(("startAt", "endAt", "windows", "expected"), [
  (datetime(2026, 11, 23, 9), datetime(2026, 11, 23, 18), standardWindows(23), 8),
  (datetime(2026, 11, 23, 11), datetime(2026, 11, 23, 14), standardWindows(23), 2),
  (datetime(2026, 11, 23, 12), datetime(2026, 11, 23, 13), standardWindows(23), 0),
  (datetime(2026, 11, 23, 9), datetime(2026, 11, 25, 18), standardWindows(23) + standardWindows(25), 16),
  (datetime(2026, 11, 23, 22), datetime(2026, 11, 24, 6), nightWindows, 7),
  (datetime(2026, 11, 24, 0), datetime(2026, 11, 24, 6), nightWindows, 5),
  (datetime(2026, 11, 28, 9), datetime(2026, 11, 28, 18), [], 0),
])
def testCountLeaveHours(startAt, endAt, windows, expected):
  assert rules.countLeaveHours(startAt, endAt, windows) == expected


def testCountLeaveHoursRejectsNonWholeHour():
  error = expectError("VALIDATION", rules.countLeaveHours, datetime(2026, 11, 23, 9, 30), datetime(2026, 11, 23, 18), [])
  assert error.details == {"field": "startAt"}


def testPeriodForRequestEndingAtMidnightStaysInYear():
  period = rules.periodForRequest("yearly_cap", 112, date(2025, 1, 1), datetime(2026, 12, 31, 9), datetime(2027, 1, 1, 0))
  assert period == Period(date(2026, 1, 1), date(2026, 12, 31), 112)


def testPeriodForRequestCrossingYearRejected():
  expectError("LEAVE_CROSSES_PERIOD", rules.periodForRequest, "yearly_cap", 112, date(2025, 1, 1), datetime(2026, 12, 31, 9), datetime(2027, 1, 4, 18))


def testPeriodForRequestCrossingAnniversaryRejected():
  expectError("LEAVE_CROSSES_PERIOD", rules.periodForRequest, "seniority", None, date(2025, 1, 1), datetime(2026, 12, 31, 9), datetime(2027, 1, 1, 18))


def testPeriodForRequestBeforeSixMonthsNotEligible():
  expectError("LEAVE_NOT_ELIGIBLE", rules.periodForRequest, "seniority", None, date(2025, 1, 1), datetime(2025, 3, 3, 9), datetime(2025, 3, 3, 18))
