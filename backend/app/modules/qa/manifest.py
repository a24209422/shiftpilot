from pathlib import Path

from app.infra.registry import ModuleManifest

# migrations 目錄是刻意不建的：問答沒有自己的資料表，資料每題複製進沙盒的暫存表
qaManifest = ModuleManifest(
  "qa",
  "問答",
  ("org", "booking", "leave", "shift"),
  ("qa.ask",),
  Path(__file__).parent / "migrations",
)
