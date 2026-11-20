from pathlib import Path

from app.infra.registry import ModuleManifest

orgManifest = ModuleManifest("org", "組織", (), ("org.read", "org.manage"), Path(__file__).parent / "migrations")
