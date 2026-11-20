from app.infra.registry import ModuleManifest
from app.modules.org.manifest import orgManifest

# 順序由各模組的 dependsOn 決定，不是這裡的排列
allModules: list[ModuleManifest] = [orgManifest]
