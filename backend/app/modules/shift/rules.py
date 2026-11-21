from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from app.infra.errors import AppError


@dataclass(frozen=True)
class ShiftType:
  id: int
  name: str
  startTime: time
  endTime: time
  breakStart: time | None = None
  breakEnd: time | None = None


@dataclass(frozen=True)
class EmployeeDates:
  hiredOn: date
  leftOn: date | None
  isActive: bool


@dataclass(frozen=True)
class Roster:
  effectiveFrom: date
  # 星期幾（0＝週一）對班別 id；沒列出的就是休息
  days: dict[int, int]


@dataclass(frozen=True)
class Override:
  # None 代表那天休息
  shiftTypeId: int | None
  note: str


@dataclass(frozen=True)
class ResolvedDay:
  day: date
  source: str
  shift: ShiftType | None = None
  startAt: datetime | None = None
  endAt: datetime | None = None
  breakStartAt: datetime | None = None
  breakEndAt: datetime | None = None
  holidayName: str | None = None
  overrideNote: str | None = None


def shiftTimes(day: date, shift: ShiftType) -> tuple[datetime, datetime, datetime | None, datetime | None]:
  startAt = datetime.combine(day, shift.startTime)
  endAt = datetime.combine(day, shift.endTime)
  # 跨日班算在開始那天，下班時間落在隔天
  if endAt <= startAt:
    endAt += timedelta(days=1)
  if shift.breakStart is None or shift.breakEnd is None:
    return startAt, endAt, None, None
  breakStartAt = datetime.combine(day, shift.breakStart)
  if breakStartAt < startAt:
    breakStartAt += timedelta(days=1)
  breakEndAt = datetime.combine(breakStartAt.date(), shift.breakEnd)
  if breakEndAt <= breakStartAt:
    breakEndAt += timedelta(days=1)
  return startAt, endAt, breakStartAt, breakEndAt


def validateShiftTimes(startTime: time, endTime: time, breakStart: time | None, breakEnd: time | None) -> None:
  for field, value in (("startTime", startTime), ("endTime", endTime), ("breakStart", breakStart), ("breakEnd", breakEnd)):
    # 請假以整點小時計算，半點的班會讓請假算出半小時
    if value is not None and (value.minute or value.second or value.microsecond):
      raise AppError("VALIDATION", "班別時間必須是整點", 422, {"field": field})
  if startTime == endTime:
    raise AppError("VALIDATION", "上班與下班時間不能相同", 422, {"field": "endTime"})
  if (breakStart is None) != (breakEnd is None):
    raise AppError("VALIDATION", "休息時間的開始與結束要一起填", 422, {"field": "breakEnd"})
  if breakStart is None:
    return
  startAt, endAt, breakStartAt, breakEndAt = shiftTimes(date(2000, 1, 3), ShiftType(0, "", startTime, endTime, breakStart, breakEnd))
  inside = startAt <= breakStartAt and breakEndAt <= endAt
  # 休息蓋滿整個班等於沒有上班時間
  if not inside or (breakStartAt == startAt and breakEndAt == endAt):
    raise AppError("VALIDATION", "休息時間要落在班內，而且不能蓋滿整個班", 422, {"field": "breakStart"})


def activeRoster(rosters: list[Roster], day: date) -> Roster | None:
  current = None
  for roster in rosters:
    if roster.effectiveFrom > day:
      break
    current = roster
  return current


def withShift(day: date, source: str, shift: ShiftType | None, holidayName: str | None = None, overrideNote: str | None = None) -> ResolvedDay:
  if shift is None:
    return ResolvedDay(day, source, holidayName=holidayName, overrideNote=overrideNote)
  startAt, endAt, breakStartAt, breakEndAt = shiftTimes(day, shift)
  return ResolvedDay(day, source, shift, startAt, endAt, breakStartAt, breakEndAt, holidayName, overrideNote)


def resolveDay(
  day: date,
  employee: EmployeeDates,
  override: Override | None,
  roster: Roster | None,
  calendarDay: tuple[str, str] | None,
  shiftTypes: dict[int, ShiftType],
  defaultShift: ShiftType | None,
) -> ResolvedDay:
  beforeHire = day < employee.hiredOn
  # 有離職日時，離職前的日子照常推算，歷史才查得回來
  afterLeave = employee.leftOn is not None and day > employee.leftOn
  inactiveWithoutDate = employee.leftOn is None and not employee.isActive
  if beforeHire or afterLeave or inactiveWithoutDate:
    return ResolvedDay(day, "inactive")
  kind, name = calendarDay if calendarDay is not None else (None, None)
  holidayName = name if kind == "holiday" else None
  if override is not None:
    shift = shiftTypes[override.shiftTypeId] if override.shiftTypeId is not None else None
    return withShift(day, "override", shift, holidayName, override.note)
  if holidayName is not None:
    return ResolvedDay(day, "holiday", holidayName=holidayName)
  isMakeup = kind == "makeup_workday"
  if roster is not None:
    shiftTypeId = roster.days.get(day.weekday())
    if shiftTypeId is not None:
      return withShift(day, "roster", shiftTypes[shiftTypeId])
    if not isMakeup:
      return ResolvedDay(day, "roster")
  if (day.weekday() < 5 or isMakeup) and defaultShift is not None:
    return withShift(day, "default", defaultShift)
  return ResolvedDay(day, "off")


def workWindowsOf(resolved: ResolvedDay) -> list[tuple[datetime, datetime]]:
  if resolved.startAt is None or resolved.endAt is None:
    return []
  if resolved.breakStartAt is None or resolved.breakEndAt is None:
    return [(resolved.startAt, resolved.endAt)]
  windows = [(resolved.startAt, resolved.breakStartAt), (resolved.breakEndAt, resolved.endAt)]
  return [window for window in windows if window[1] > window[0]]


def clipWindows(windows: list[tuple[datetime, datetime]], startAt: datetime, endAt: datetime) -> list[tuple[datetime, datetime]]:
  result = []
  for windowStart, windowEnd in windows:
    start = max(windowStart, startAt)
    end = min(windowEnd, endAt)
    if end > start:
      result.append((start, end))
  return sorted(result)


def isCovered(startAt: datetime, endAt: datetime, spans: list[tuple[datetime, datetime]]) -> bool:
  cursor = startAt
  for spanStart, spanEnd in sorted(spans):
    if spanStart > cursor:
      break
    cursor = max(cursor, spanEnd)
    if cursor >= endAt:
      return True
  return cursor >= endAt
