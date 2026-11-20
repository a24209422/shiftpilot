import importlib
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import loadConfig, loadEnvFile
from app.infra.actor import Actor
from app.infra.errors import AppError
from app.infra.http import getActor, installHttpHandlers
from app.infra.permissions import permissionsFor
from app.modules import allModules
from app.modules.core.router import authRouter

# repo 根目錄的 frontend/dist（npm run build 的輸出）
defaultFrontendDir = Path(__file__).resolve().parents[2] / "frontend" / "dist"


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


def createApp(databaseUrl: str, sessionHours: int = 12, frontendDir: Path | None = None) -> FastAPI:
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

  if frontendDir is not None and (frontendDir / "index.html").is_file():
    mountFrontend(app, frontendDir)
  return app


def mountFrontend(app: FastAPI, dist: Path) -> None:
  root = dist.resolve()
  app.mount("/assets", StaticFiles(directory=root / "assets", check_dir=False), name="assets")

  # 放在所有 API 路由之後：前端路由（/bookings 這類）重新整理時要拿到 index.html，交給前端的路由處理
  @app.get("/{fullPath:path}", include_in_schema=False)
  def serveFrontend(fullPath: str):
    if fullPath == "api" or fullPath.startswith("api/"):
      raise AppError("NOT_FOUND", "找不到這個 API", 404)
    candidate = (root / fullPath).resolve()
    # 解析後必須還在 dist 裡面，擋掉 ../ 跳出資料夾讀其他檔案
    if candidate.is_file() and candidate.is_relative_to(root):
      return FileResponse(candidate)
    return FileResponse(root / "index.html")


def createAppFromEnv() -> FastAPI:
  # 給 uvicorn --factory 用；README 的啟動指令不會先 export 環境變數，所以要自己讀 .env
  loadEnvFile()
  config = loadConfig()
  return createApp(config.databaseUrl, config.sessionHours, defaultFrontendDir)
