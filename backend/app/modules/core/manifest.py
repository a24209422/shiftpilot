from pathlib import Path

from app.infra.registry import ModuleManifest

coreManifest = ModuleManifest(
  "core", "帳號與稽核", ("org",), ("core.users.manage", "core.audit.read"), Path(__file__).parent / "migrations"
)
