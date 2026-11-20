from pathlib import Path

from app.infra.registry import ModuleManifest

bookingManifest = ModuleManifest(
  "booking",
  "資源預約",
  ("org", "core"),
  ("booking.read", "booking.write", "booking.writeAny", "booking.resources.manage"),
  Path(__file__).parent / "migrations",
)
