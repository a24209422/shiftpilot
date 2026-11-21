from datetime import date, datetime, time

import pytest

from app.infra.errors import AppError
from app.modules.shift import rules
from app.modules.shift.rules import EmployeeDates, Override, Roster, ShiftType

standard = ShiftType(1, "標準班", time(9), time(18), time(12), time(13))
evening = ShiftType(2, "晚班", time(14), time(23), time(18), time(19))
night = ShiftType(3, "大夜班", time(22), time(6), time(2), time(3))
types = {1: standard, 2: evening, 3: night}
active = EmployeeDates(date(2025, 1, 1), None, True)


def dt(day, hour):
  return datetime(2026, 11, day, hour)


def resolve(day, employee=active, override=None, roster=None, calendarDay=None, defaultShift=standard):
  return rules.resolveDay(day, employee, override, roster, calendarDay, types, defaultShift)


def expectError(call, *args):
  with pytest.raises(AppError) as info:
    call(*args)
  assert info.value.code == "VALIDATION"
  return info.value


def testShiftTimesForDayShift():
  assert rules.shiftTimes(date(2026, 11, 23), standard) == (dt(23, 9), dt(23, 18), dt(23, 12), dt(23, 13))


def testShiftTimesForCrossMidnightShift():
  assert rules.shiftTimes(date(2026, 11, 23), night) == (dt(23, 22), dt(24, 6), dt(24, 2), dt(24, 3))


def testShiftTimesWithoutBreak():
  plain = ShiftType(4, "短班", time(10), time(14))
  assert rules.shiftTimes(date(2026, 11, 23), plain) == (dt(23, 10), dt(23, 14), None, None)


@pytest.mark.parametrize(("start", "end", "breakStart", "breakEnd", "field"), [
  (time(8, 30), time(17), None, None, "startTime"),
  (time(9), time(9), None, None, "endTime"),
  (time(9), time(18), time(12), None, "breakEnd"),
  (time(9), time(18), time(20), time(21), "breakStart"),
  (time(9), time(18), time(8), time(9), "breakStart"),
  (time(22), time(6), time(5), time(7), "breakStart"),
  (time(9), time(18), time(9), time(18), "breakStart"),
])
def testValidateShiftTimesRejects(start, end, breakStart, breakEnd, field):
  assert expectError(rules.validateShiftTimes, start, end, breakStart, breakEnd).details == {"field": field}


def testValidateShiftTimesAccepts():
  rules.validateShiftTimes(time(9), time(18), time(12), time(13))
  rules.validateShiftTimes(time(22), time(6), time(2), time(3))
  rules.validateShiftTimes(time(22), time(6), time(23), time(0))
  rules.validateShiftTimes(time(10), time(14), None, None)


def testActiveRosterPicksLatestEffective():
  first = Roster(date(2026, 1, 1), {0: 2})
  second = Roster(date(2026, 11, 25), {0: 3})
  assert rules.activeRoster([first, second], date(2025, 12, 31)) is None
  assert rules.activeRoster([first, second], date(2026, 11, 24)) == first
  assert rules.activeRoster([first, second], date(2026, 11, 25)) == second


# 2026-11-23 是星期一、11-28 是星期六
def testDefaultShiftOnWeekdaysOffOnWeekend():
  monday = resolve(date(2026, 11, 23))
  assert monday.source == "default" and monday.shift == standard and monday.startAt == dt(23, 9) and monday.endAt == dt(23, 18)
  assert resolve(date(2026, 11, 28)).source == "off"


def testMakeupWorkdayUsesDefaultShift():
  assert resolve(date(2026, 11, 28), calendarDay=("makeup_workday", "補班")).source == "default"


def testHolidayIsOff():
  day = resolve(date(2026, 11, 25), calendarDay=("holiday", "測試假日"))
  assert day.source == "holiday" and day.holidayName == "測試假日" and day.shift is None


def testRosterOverridesDefault():
  roster = Roster(date(2026, 11, 23), {0: 2, 5: 2})
  monday = resolve(date(2026, 11, 23), roster=roster)
  assert monday.source == "roster" and monday.shift == evening and monday.startAt == dt(23, 14)
  tuesday = resolve(date(2026, 11, 24), roster=roster)
  assert tuesday.source == "roster" and tuesday.shift is None
  assert resolve(date(2026, 11, 28), roster=roster).shift == evening


def testHolidayBeatsRoster():
  roster = Roster(date(2026, 11, 23), {2: 2})
  assert resolve(date(2026, 11, 25), roster=roster, calendarDay=("holiday", "測試假日")).source == "holiday"


def testMakeupDayFallsBackToDefaultWhenRosterRests():
  roster = Roster(date(2026, 11, 23), {0: 2})
  day = resolve(date(2026, 11, 28), roster=roster, calendarDay=("makeup_workday", "補班"))
  assert day.source == "default" and day.shift == standard


def testOverrideBeatsHolidayAndRoster():
  roster = Roster(date(2026, 11, 23), {2: 2})
  day = resolve(date(2026, 11, 25), override=Override(3, "支援"), roster=roster, calendarDay=("holiday", "測試假日"))
  assert day.source == "override" and day.shift == night and day.holidayName == "測試假日" and day.overrideNote == "支援"
  rest = resolve(date(2026, 11, 23), override=Override(None, "補休"))
  assert rest.source == "override" and rest.shift is None and rest.startAt is None


@pytest.mark.parametrize(("employee", "day", "expected"), [
  (EmployeeDates(date(2026, 11, 25), None, True), date(2026, 11, 24), "inactive"),
  (EmployeeDates(date(2025, 1, 1), date(2026, 11, 24), False), date(2026, 11, 24), "default"),
  (EmployeeDates(date(2025, 1, 1), date(2026, 11, 24), False), date(2026, 11, 25), "inactive"),
  (EmployeeDates(date(2025, 1, 1), None, False), date(2026, 11, 23), "inactive"),
])
def testInactiveDays(employee, day, expected):
  assert resolve(day, employee=employee).source == expected


def testInactiveBeatsOverride():
  employee = EmployeeDates(date(2026, 11, 25), None, True)
  assert resolve(date(2026, 11, 24), employee=employee, override=Override(2, "")).source == "inactive"


def testNoDefaultShiftMeansOff():
  assert resolve(date(2026, 11, 23), defaultShift=None).source == "off"
  roster = Roster(date(2026, 11, 23), {0: 2})
  assert resolve(date(2026, 11, 28), roster=roster, calendarDay=("makeup_workday", "補班"), defaultShift=None).shift is None


def testWorkWindowsSubtractBreak():
  assert rules.workWindowsOf(resolve(date(2026, 11, 23))) == [(dt(23, 9), dt(23, 12)), (dt(23, 13), dt(23, 18))]
  nightDay = resolve(date(2026, 11, 23), roster=Roster(date(2026, 11, 23), {0: 3}))
  assert rules.workWindowsOf(nightDay) == [(dt(23, 22), dt(24, 2)), (dt(24, 3), dt(24, 6))]
  assert rules.workWindowsOf(resolve(date(2026, 11, 28))) == []


def testClipWindows():
  windows = [(dt(23, 9), dt(23, 12)), (dt(23, 13), dt(23, 18))]
  assert rules.clipWindows(windows, dt(23, 11), dt(23, 14)) == [(dt(23, 11), dt(23, 12)), (dt(23, 13), dt(23, 14))]
  assert rules.clipWindows(windows, dt(23, 18), dt(23, 20)) == []


def testIsCovered():
  spans = [(dt(23, 9), dt(23, 18))]
  assert rules.isCovered(dt(23, 10), dt(23, 11), spans)
  assert rules.isCovered(dt(23, 12), dt(23, 13), spans)
  assert not rules.isCovered(dt(23, 17), dt(23, 19), spans)
  assert not rules.isCovered(dt(23, 8), dt(23, 10), spans)
  assert rules.isCovered(dt(24, 1), dt(24, 5), [(dt(23, 22), dt(24, 6))])
  assert rules.isCovered(dt(23, 17), dt(23, 23), [(dt(23, 9), dt(23, 18)), (dt(23, 18), dt(24, 2))])
  assert not rules.isCovered(dt(23, 10), dt(23, 11), [])
