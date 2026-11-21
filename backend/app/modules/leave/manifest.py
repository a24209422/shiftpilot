from pathlib import Path

from app.infra.registry import ModuleManifest

# 依賴 booking：送出申請時要查本人同時段的會議；依賴 shift：時數依各人的班計算
leaveManifest = ModuleManifest(
  "leave",
  "請假",
  ("org", "core", "booking", "shift"),
  ("leave.request", "leave.manage"),
  Path(__file__).parent / "migrations",
)
