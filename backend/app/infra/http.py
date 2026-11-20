from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.infra.actor import Actor
from app.infra.db import openDb
from app.infra.errors import AppError
from app.infra.permissions import hasPermission

sessionCookieName = "sid"
csrfHeaderName = "X-App-Client"
csrfHeaderValue = "web"
safeMethods = {"GET", "HEAD", "OPTIONS"}


def errorResponse(status: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
  return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "details": details}})


def getConn(request: Request):
  # 一個請求一個交易：正常結束 commit，例外時 rollback；FastAPI 會把端點的例外丟回這裡
  with openDb(request.app.state.databaseUrl) as conn:
    yield conn


def getActor(request: Request, conn=Depends(getConn)) -> Actor:
  # 函式內才匯入：core 模組的 service 也會用到 infra，避免啟動時互相匯入
  from app.modules.core.service import getSessionActor

  token = request.cookies.get(sessionCookieName)
  actor = getSessionActor(conn, token) if token else None
  if actor is None:
    raise AppError("UNAUTHENTICATED", "請先登入", 401)
  return actor


def requirePermission(permission: str):
  def check(actor: Actor = Depends(getActor)) -> Actor:
    # 每個 API 動作都在這裡檢查；只靠前端把按鈕藏起來不算有檢查
    if not hasPermission(actor.role, permission):
      raise AppError("FORBIDDEN", "沒有權限執行這個動作", 403)
    return actor

  return check


def installHttpHandlers(app: FastAPI) -> None:
  @app.middleware("http")
  async def requireCsrfHeader(request: Request, callNext):
    # SameSite=Lax 之外再要求自訂標頭：跨站的表單和 <img> 帶不出自訂標頭，瀏覽器對 fetch 帶自訂標頭又會先做預檢
    if request.method not in safeMethods and request.headers.get(csrfHeaderName) != csrfHeaderValue:
      return errorResponse(403, "CSRF", f"請求缺少標頭 {csrfHeaderName}: {csrfHeaderValue}")
    return await callNext(request)

  @app.exception_handler(AppError)
  async def handleAppError(request: Request, error: AppError):
    return errorResponse(error.status, error.code, error.message, error.details)

  @app.exception_handler(RequestValidationError)
  async def handleValidationError(request: Request, error: RequestValidationError):
    fields = [{"loc": [str(part) for part in item["loc"]], "message": item["msg"]} for item in error.errors()]
    return errorResponse(422, "VALIDATION", "請求內容不符合格式", {"fields": fields})

  @app.exception_handler(StarletteHTTPException)
  async def handleHttpError(request: Request, error: StarletteHTTPException):
    code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(error.status_code, f"HTTP_{error.status_code}")
    return errorResponse(error.status_code, code, str(error.detail))
