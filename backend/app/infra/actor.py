from dataclasses import dataclass


@dataclass(frozen=True)
class Actor:
  userId: int
  role: str
  employeeId: int | None
