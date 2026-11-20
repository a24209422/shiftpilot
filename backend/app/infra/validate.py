from app.infra.errors import AppError


def requireText(value, label: str) -> str:
  if not isinstance(value, str) or not value.strip():
    raise AppError("VALIDATION", f"{label}不能是空白", 422)
  return value.strip()
