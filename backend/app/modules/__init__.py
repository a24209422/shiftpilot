from app.infra.registry import ModuleManifest

# 每個模組的任務會把自己的 manifest 加進來；順序由 dependsOn 決定，不是這裡的排列
allModules: list[ModuleManifest] = []
