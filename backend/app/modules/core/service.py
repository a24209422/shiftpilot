import json

from psycopg import Connection

from app.infra.actor import Actor
from app.infra.serialize import camelizeRow


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
