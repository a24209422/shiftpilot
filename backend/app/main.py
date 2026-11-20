import importlib

from fastapi import Depends, FastAPI

from app.config import loadConfig
from app.infra.actor import Actor
from app.infra.http import getActor, installHttpHandlers
from app.infra.permissions import permissionsFor
from app.modules import allModules
from app.modules.core.router import authRouter


def mountModuleRouters(app: FastAPI) -> None:
  for manifest in allModules:
    moduleName = f"app.modules.{manifest.name}.router"
    try:
      module = importlib.import_module(moduleName)
    except ModuleNotFoundError as error:
      # 只略過「這個模組還沒有 router.py」；router.py 裡自己匯入失敗要讓它照常報錯
      if error.name == moduleName:
        continue
      raise
    app.include_router(module.router, prefix=f"/api/{manifest.name}")


def createApp(databaseUrl: str, sessionHours: int = 12) -> FastAPI:
  app = FastAPI(title="請假排班系統")
  app.state.databaseUrl = databaseUrl
  app.state.sessionHours = sessionHours
  installHttpHandlers(app)
  app.include_router(authRouter, prefix="/api/auth")
  mountModuleRouters(app)

  @app.get("/api/modules")
  def listVisibleModules(actor: Actor = Depends(getActor)):
    granted = permissionsFor(actor.role)
    visible = []
    for manifest in allModules:
      # 使用者在這個模組一項權限都沒有，就不列出
      owned = [name for name in manifest.permissions if name in granted]
      if owned:
        visible.append({"name": manifest.name, "title": manifest.title, "permissions": owned})
    return visible

  return app


def createAppFromEnv() -> FastAPI:
  # 給 uvicorn --factory 用
  config = loadConfig()
  return createApp(config.databaseUrl, config.sessionHours)
