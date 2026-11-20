import json
from datetime import datetime, timedelta

from psycopg import Connection

from app.infra.actor import Actor
from app.infra.db import mapDbErrors
from app.infra.errors import AppError
from app.infra.serialize import camelizeRow
from app.modules.core.security import hashPassword, hashToken, newSessionToken, verifyPassword

validRoles = {"employee", "manager", "hr", "admin"}
minPasswordLength = 8
maxPasswordLength = 128
maxFailedLogins = 5
lockMinutes = 15

userColumns = (
  "u.id, u.email, u.role, u.employee_id, e.name AS employee_name, u.is_active, u.last_login_at, u.locked_until, u.created_at"
)
userFrom = "FROM users u LEFT JOIN employees e ON e.id = u.employee_id"

# 帳號不存在時也要做一次雜湊比對，回應時間才不會洩漏「這個 email 有沒有註冊」
dummyHash = hashPassword("dummy-password-for-timing")


def toJson(value: dict | None) -> str | None:
  if value is None:
    return None
  # 日期等不能直接轉 JSON 的值用 str；中文不轉義，稽核紀錄才看得懂
  return json.dumps(value, default=str, ensure_ascii=False)


def writeAudit(
  conn: Connection,
  actor: Actor | None,
  module: str,
  action: str,
  entity: str,
  entityId: int | str,
  before: dict | None,
  after: dict | None,
) -> int:
  row = conn.execute(
    "INSERT INTO audit_log (user_id, module, action, entity, entity_id, before, after) "
    "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb) RETURNING id",
    (actor.userId if actor else None, module, action, entity, str(entityId), toJson(before), toJson(after)),
  ).fetchone()
  return row["id"]


def listAudit(conn: Connection, module: str | None = None, limit: int = 100, beforeId: int | None = None) -> list[dict]:
  rows = conn.execute(
    "SELECT id, at, user_id, module, action, entity, entity_id, before, after FROM audit_log "
    "WHERE (%(module)s::text IS NULL OR module = %(module)s) AND (%(beforeId)s::int IS NULL OR id < %(beforeId)s) "
    "ORDER BY id DESC LIMIT %(limit)s",
    {"module": module, "beforeId": beforeId, "limit": limit},
  ).fetchall()
  result = []
  for row in rows:
    # before、after 是當時存下的內容，原樣回傳；只轉外層欄位名稱
    snapshot = {"before": row.pop("before"), "after": row.pop("after")}
    result.append({**camelizeRow(row), **snapshot})
  return result


def invalidCredentials() -> AppError:
  # 帳號不存在、密碼錯誤、帳號停用都回同一個訊息，不讓人從回應猜出哪些帳號存在
  return AppError("INVALID_CREDENTIALS", "帳號或密碼錯誤", 401)


def checkPasswordLength(password) -> None:
  if not isinstance(password, str) or not minPasswordLength <= len(password) <= maxPasswordLength:
    raise AppError("VALIDATION", f"密碼長度必須是 {minPasswordLength} 到 {maxPasswordLength} 個字元", 422, {"field": "password"})


def getUser(conn: Connection, userId: int) -> dict:
  row = conn.execute(f"SELECT {userColumns} {userFrom} WHERE u.id = %s", (userId,)).fetchone()
  if row is None:
    raise AppError("NOT_FOUND", "找不到使用者", 404)
  return camelizeRow(row)


def listUsers(conn: Connection) -> list[dict]:
  return camelizeRow(conn.execute(f"SELECT {userColumns} {userFrom} ORDER BY u.id").fetchall())


def createUser(
  conn: Connection, actor: Actor | None, email: str, password: str, role: str, employeeId: int | None = None
) -> dict:
  email = email.strip() if isinstance(email, str) else ""
  if not email:
    raise AppError("VALIDATION", "email 不能是空白", 422, {"field": "email"})
  if role not in validRoles:
    raise AppError("VALIDATION", f"role 只能是 {', '.join(sorted(validRoles))}", 422, {"field": "role"})
  checkPasswordLength(password)
  with mapDbErrors(conn):
    row = conn.execute(
      "INSERT INTO users (email, password_hash, role, employee_id) VALUES (%s, %s, %s, %s) RETURNING id",
      (email, hashPassword(password), role, employeeId),
    ).fetchone()
  user = getUser(conn, row["id"])
  # 稽核只放 getUser 的欄位：那裡沒有密碼也沒有雜湊
  writeAudit(conn, actor, "core", "createUser", "user", user["id"], None, user)
  return user


def authenticate(conn: Connection, email: str, password: str, now: datetime | None = None) -> dict:
  now = now or datetime.now()
  row = conn.execute(
    "SELECT id, password_hash, is_active, failed_login_count, locked_until FROM users "
    "WHERE lower(email) = lower(%s) FOR UPDATE",
    (email.strip(),),
  ).fetchone()
  if row is None or not row["is_active"]:
    verifyPassword(dummyHash, password)
    raise invalidCredentials()
  if row["locked_until"] is not None and row["locked_until"] > now:
    raise AppError("TOO_MANY_ATTEMPTS", "登入失敗次數過多，請稍後再試", 429)
  if not verifyPassword(row["password_hash"], password):
    failed = row["failed_login_count"] + 1
    lockedUntil = now + timedelta(minutes=lockMinutes) if failed >= maxFailedLogins else None
    conn.execute(
      "UPDATE users SET failed_login_count = %s, locked_until = %s WHERE id = %s",
      (0 if lockedUntil else failed, lockedUntil, row["id"]),
    )
    # 接著要丟錯誤，HTTP 層遇到錯誤會 rollback；不先 commit，失敗次數就永遠累積不起來
    conn.commit()
    raise invalidCredentials()
  conn.execute(
    "UPDATE users SET failed_login_count = 0, locked_until = NULL, last_login_at = %s WHERE id = %s", (now, row["id"])
  )
  return getUser(conn, row["id"])


def createSession(conn: Connection, userId: int, hours: int = 12, now: datetime | None = None) -> str:
  now = now or datetime.now()
  # 順手清掉過期的，sessions 表才不會一直長大
  conn.execute("DELETE FROM sessions WHERE expires_at < %s", (now,))
  token = newSessionToken()
  conn.execute(
    "INSERT INTO sessions (id_hash, user_id, expires_at) VALUES (%s, %s, %s)",
    (hashToken(token), userId, now + timedelta(hours=hours)),
  )
  return token


def getSessionActor(conn: Connection, token: str, now: datetime | None = None) -> Actor | None:
  now = now or datetime.now()
  row = conn.execute(
    "SELECT u.id, u.role, u.employee_id FROM sessions s JOIN users u ON u.id = s.user_id "
    "WHERE s.id_hash = %s AND s.expires_at > %s AND u.is_active",
    (hashToken(token), now),
  ).fetchone()
  if row is None:
    return None
  return Actor(userId=row["id"], role=row["role"], employeeId=row["employee_id"])


def deleteSession(conn: Connection, token: str) -> None:
  conn.execute("DELETE FROM sessions WHERE id_hash = %s", (hashToken(token),))


def changePassword(conn: Connection, actor: Actor, currentPassword: str, newPassword: str) -> None:
  checkPasswordLength(newPassword)
  row = conn.execute("SELECT password_hash FROM users WHERE id = %s", (actor.userId,)).fetchone()
  # 用 422 而不是 401：前端把 401 當成「登入過期」，已登入的人輸錯目前密碼不該被踢回登入頁
  if row is None or not verifyPassword(row["password_hash"], currentPassword):
    raise AppError("VALIDATION", "目前的密碼不正確", 422, {"field": "currentPassword"})
  conn.execute("UPDATE users SET password_hash = %s WHERE id = %s", (hashPassword(newPassword), actor.userId))
  conn.execute("DELETE FROM sessions WHERE user_id = %s", (actor.userId,))
  writeAudit(conn, actor, "core", "changePassword", "user", actor.userId, None, None)


def resetPassword(conn: Connection, actor: Actor, userId: int, newPassword: str) -> None:
  checkPasswordLength(newPassword)
  row = conn.execute(
    "UPDATE users SET password_hash = %s, failed_login_count = 0, locked_until = NULL WHERE id = %s RETURNING id",
    (hashPassword(newPassword), userId),
  ).fetchone()
  if row is None:
    raise AppError("NOT_FOUND", "找不到使用者", 404)
  conn.execute("DELETE FROM sessions WHERE user_id = %s", (userId,))
  writeAudit(conn, actor, "core", "resetPassword", "user", userId, None, None)


updatableUserFields = {"role": "role", "isActive": "is_active", "employeeId": "employee_id"}


def updateUser(conn: Connection, actor: Actor, userId: int, fields: dict) -> dict:
  unknown = set(fields) - set(updatableUserFields)
  if unknown:
    raise AppError("VALIDATION", f"不能修改的欄位：{', '.join(sorted(unknown))}", 422)
  if "role" in fields and fields["role"] not in validRoles:
    raise AppError("VALIDATION", f"role 只能是 {', '.join(sorted(validRoles))}", 422, {"field": "role"})
  before = getUser(conn, userId)
  # 管理員改掉自己的角色或停用自己，可能讓系統沒有任何管理員
  if userId == actor.userId and (("role" in fields and fields["role"] != before["role"]) or fields.get("isActive") is False):
    raise AppError("CANNOT_MODIFY_SELF", "不能修改自己的角色或停用自己的帳號", 422)
  if not fields:
    return before
  assignments = ", ".join(f"{updatableUserFields[key]} = %s" for key in fields)
  with mapDbErrors(conn):
    conn.execute(f"UPDATE users SET {assignments} WHERE id = %s", [*fields.values(), userId])
  if fields.get("isActive") is False:
    conn.execute("DELETE FROM sessions WHERE user_id = %s", (userId,))
  after = getUser(conn, userId)
  writeAudit(conn, actor, "core", "updateUser", "user", userId, before, after)
  return after
