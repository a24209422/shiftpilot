import calendar
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from app.infra.errors import AppError

hoursPerDay = 8
# 排班模組做好之前，所有人都用固定的上班時間；之後改成依各自的班表計算
workWindows = ((time(9), time(12)), (time(13), time(18)))


@dataclass(frozen=True)
class Period:
  start: date
  # 含這一天
  end: date
  # None 代表不限額度
  quotaHours: int | None


def addMonths(day: date, months: int) -> date:
  yearOffset, monthIndex = divmod(day.month - 1 + months, 12)
  year = day.year + yearOffset
  month = monthIndex + 1
  # 8/31 加 6 個月沒有 2/31，依設計書的約定取該月最後一天
  return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def annualLeaveDays(years: int) -> int:
  # 勞基法第 38 條；years 是滿幾年，至少 1
  if years == 1:
    return 7
  if years == 2:
    return 10
  if years <= 4:
    return 14
  if years <= 9:
    return 15
  return min(30, 15 + years - 9)


def seniorityPeriod(hiredOn: date, day: date) -> Period | None:
  halfYear = addMonths(hiredOn, 6)
  if day < halfYear:
    return None
  firstYear = addMonths(hiredOn, 12)
  if day < firstYear:
    return Period(halfYear, firstYear - timedelta(days=1), 3 * hoursPerDay)
  years = day.year - hiredOn.year
  if addMonths(hiredOn, 12 * years) > day:
    years -= 1
  start = addMonths(hiredOn, 12 * years)
  end = addMonths(hiredOn, 12 * (years + 1)) - timedelta(days=1)
  return Period(start, end, annualLeaveDays(years) * hoursPerDay)


def periodFor(quotaKind: str, annualCapHours: int | None, hiredOn: date, day: date) -> Period | None:
  if quotaKind == "seniority":
    return seniorityPeriod(hiredOn, day)
  # 特休以外的假別，年度上限以曆年計
  quota = annualCapHours if quotaKind == "yearly_cap" else None
  return Period(date(day.year, 1, 1), date(day.year, 12, 31), quota)


def isWorkday(day: date, calendarKinds: dict[date, str]) -> bool:
  kind = calendarKinds.get(day)
  if kind == "holiday":
    return False
  if kind == "makeup_workday":
    return True
  return day.weekday() < 5


def requireWholeHour(value: datetime, field: str) -> None:
  if value.minute or value.second or value.microsecond:
    raise AppError("VALIDATION", "請假時間必須是整點", 422, {"field": field})


def countLeaveHours(startAt: datetime, endAt: datetime, calendarKinds: dict[date, str]) -> int:
  requireWholeHour(startAt, "startAt")
  requireWholeHour(endAt, "endAt")
  total = timedelta()
  day = startAt.date()
  while day <= endAt.date():
    if isWorkday(day, calendarKinds):
      for windowStart, windowEnd in workWindows:
        start = max(startAt, datetime.combine(day, windowStart))
        end = min(endAt, datetime.combine(day, windowEnd))
        if end > start:
          total += end - start
    day += timedelta(days=1)
  return int(total.total_seconds() // 3600)


def periodForRequest(quotaKind: str, annualCapHours: int | None, hiredOn: date, startAt: datetime, endAt: datetime) -> Period:
  first = periodFor(quotaKind, annualCapHours, hiredOn, startAt.date())
  if first is None:
    raise AppError("LEAVE_NOT_ELIGIBLE", "到職未滿 6 個月，還沒有特休", 422)
  # 結束在 00:00 時，實際的最後一天是前一天
  last = periodFor(quotaKind, annualCapHours, hiredOn, (endAt - timedelta(microseconds=1)).date())
  if last != first:
    raise AppError(
      "LEAVE_CROSSES_PERIOD", f"這段時間跨了兩個年度（這個年度到 {first.end.isoformat()} 為止），請拆成兩張申請", 422,
    )
  return first
