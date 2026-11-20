import re
from datetime import date, datetime

from app.infra.errors import AppError

localTimePattern = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$")


def snakeToCamel(name: str) -> str:
  head, *rest = name.split("_")
  return head + "".join(part.capitalize() for part in rest)


def camelizeRow(value):
  # datetime 是 date 的子類別，要先判斷
  if isinstance(value, datetime):
    return value.isoformat(timespec="seconds")
  if isinstance(value, date):
    return value.isoformat()
  if isinstance(value, dict):
    return {snakeToCamel(key): camelizeRow(item) for key, item in value.items()}
  if isinstance(value, list):
    return [camelizeRow(item) for item in value]
  return value


def parseLocalTime(text: str) -> datetime:
  # 系統是單一時區，帶時區位移的輸入沒有明確的處理方式，直接拒絕比悄悄換算安全
  if not isinstance(text, str) or not localTimePattern.match(text):
    raise AppError("VALIDATION", "時間格式必須是 YYYY-MM-DDTHH:MM 或 YYYY-MM-DDTHH:MM:SS，且不含時區", 422)
  try:
    return datetime.fromisoformat(text)
  except ValueError:
    raise AppError("VALIDATION", "時間不是有效的日期", 422)
