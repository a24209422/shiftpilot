from pathlib import Path

from app.infra.registry import ModuleManifest

shiftManifest = ModuleManifest(
  "shift",
  "排班",
  ("org", "core"),
  ("shift.read", "shift.manage"),
  Path(__file__).parent / "migrations",
)
