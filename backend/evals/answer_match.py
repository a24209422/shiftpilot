"""用字串比對檢查最後的回答有沒有講到標準答案（回答分數 B）。

免費、可以重跑，但會誤判，所以只當作 LLM 評審（C）的對照。
"""
import re
from datetime import date, datetime
from decimal import Decimal

datePattern = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
dateTimePattern = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})")
emptyWords = ("查無", "沒有")


def numberText(value) -> str:
  # 回答通常不會寫多餘的 0：3.20 和 3.2、68.0 和 68 要當成同一個數字
  return format(Decimal(str(value)).normalize(), "f")


def dateForms(month: int, day: int, year: int) -> list[str]:
  return [f"{year}-{month:02d}-{day:02d}", f"{month}/{day}", f"{month}/{day:02d}", f"{month:02d}/{day:02d}",
          f"{month} 月 {day} 日", f"{month}月{day}日"]


def timeForms(hour: int, minute: int) -> list[str]:
  forms = [f"{hour}:{minute:02d}", f"{hour:02d}:{minute:02d}"]
  if minute == 0:
    forms += [f"{hour} 點", f"{hour}點"]
  return forms


def valueForms(value) -> list[list[str]] | None:
  """把一個值轉成條件：每一組都要出現，組內任一種寫法即可；None 代表這個值不比對。"""
  if value is None or isinstance(value, bool):
    return None
  if isinstance(value, (int, float, Decimal)):
    return [["#" + numberText(value)]]
  if isinstance(value, datetime):
    return [dateForms(value.month, value.day, value.year), timeForms(value.hour, value.minute)]
  if isinstance(value, date):
    return [dateForms(value.month, value.day, value.year)]
  text = str(value).strip()
  if not text:
    return None
  matched = dateTimePattern.match(text)
  if matched:
    year, month, day, hour, minute = (int(part) for part in matched.groups())
    return [dateForms(month, day, year), timeForms(hour, minute)]
  matched = datePattern.match(text)
  if matched:
    year, month, day = (int(part) for part in matched.groups())
    return [dateForms(month, day, year)]
  return [[text]]


def formAppears(form: str, answer: str) -> bool:
  if form.startswith("#"):
    # 數字前後不能緊接數字或小數點，否則「11/17」裡的 1 也會被當成數字 1
    return re.search(rf"(?<![\d.]){re.escape(form[1:])}(?![\d.])", answer) is not None
  return form in answer


def matchesRows(answer: str, rows: list[list]) -> bool:
  if not rows:
    return any(word in answer for word in emptyWords)
  for row in rows:
    for value in row:
      groups = valueForms(value)
      if groups is None:
        continue
      if not all(any(formAppears(form, answer) for form in group) for group in groups):
        return False
  return True


def matchAnswer(answer: str | None, goldResults: list[list[list]]) -> bool | None:
  if answer is None:
    return None
  return any(matchesRows(answer, rows) for rows in goldResults)
