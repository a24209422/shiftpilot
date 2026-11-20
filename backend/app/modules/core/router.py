from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel

from app.infra.actor import Actor
from app.infra.http import getActor, getConn, requirePermission, sessionCookieName
from app.modules.core import service

# 登入相關的路由掛在 /api/auth，不在 /api/core 底下（設計文件的路徑）；main.py 明確掛上這一組
authRouter = APIRouter()
# 帳號管理與稽核掛在 /api/core，由 main.py 依模組登記自動掛上
router = APIRouter()


class LoginBody(BaseModel):
  email: str
  password: str


class ChangePasswordBody(BaseModel):
  currentPassword: str
  newPassword: str


def userPayload(user: dict) -> dict:
  return {key: user[key] for key in ("id", "email", "role", "employeeId", "employeeName")}


def clearSessionCookie(response: Response) -> None:
  response.delete_cookie(sessionCookieName, path="/", httponly=True, samesite="lax")


@authRouter.post("/login")
def login(body: LoginBody, request: Request, response: Response, conn=Depends(getConn)):
  user = service.authenticate(conn, body.email, body.password)
  hours = request.app.state.sessionHours
  token = service.createSession(conn, user["id"], hours)
  # 不設 Secure：目前只綁 127.0.0.1、走 http；開放到區網時要連同 HTTPS 一起改
  response.set_cookie(sessionCookieName, token, max_age=hours * 3600, httponly=True, samesite="lax", path="/")
  return {"user": userPayload(user)}


@authRouter.post("/logout", status_code=204)
def logout(request: Request, response: Response, conn=Depends(getConn)):
  token = request.cookies.get(sessionCookieName)
  if token:
    service.deleteSession(conn, token)
  clearSessionCookie(response)


@authRouter.get("/me")
def me(actor: Actor = Depends(getActor), conn=Depends(getConn)):
  return {"user": userPayload(service.getUser(conn, actor.userId))}


@authRouter.post("/password", status_code=204)
def changePassword(body: ChangePasswordBody, response: Response, actor: Actor = Depends(getActor), conn=Depends(getConn)):
  service.changePassword(conn, actor, body.currentPassword, body.newPassword)
  # 密碼改了，所有 session（包含這一個）都已刪除，要重新登入
  clearSessionCookie(response)


manageUsers = requirePermission("core.users.manage")
readAudit = requirePermission("core.audit.read")


class UserCreate(BaseModel):
  email: str
  password: str
  role: str
  employeeId: int | None = None


class UserUpdate(BaseModel):
  role: str | None = None
  isActive: bool | None = None
  employeeId: int | None = None


class ResetPasswordBody(BaseModel):
  newPassword: str


@router.get("/users")
def listUsers(actor: Actor = Depends(manageUsers), conn=Depends(getConn)):
  return service.listUsers(conn)


@router.post("/users", status_code=201)
def createUser(body: UserCreate, actor: Actor = Depends(manageUsers), conn=Depends(getConn)):
  return service.createUser(conn, actor, body.email, body.password, body.role, body.employeeId)


@router.patch("/users/{userId}")
def updateUser(userId: int, body: UserUpdate, actor: Actor = Depends(manageUsers), conn=Depends(getConn)):
  return service.updateUser(conn, actor, userId, body.model_dump(exclude_unset=True))


@router.post("/users/{userId}/password", status_code=204)
def resetPassword(userId: int, body: ResetPasswordBody, actor: Actor = Depends(manageUsers), conn=Depends(getConn)):
  service.resetPassword(conn, actor, userId, body.newPassword)


@router.get("/audit")
def listAudit(
  module: str | None = None,
  limit: int = Query(100, ge=1, le=500),
  beforeId: int | None = None,
  actor: Actor = Depends(readAudit),
  conn=Depends(getConn),
):
  return service.listAudit(conn, module, limit, beforeId)
