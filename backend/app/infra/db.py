import uuid
from contextlib import contextmanager

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

from app.infra.errors import AppError


@contextmanager
def openDb(databaseUrl: str):
  # psycopg 的連線離開 with 時，成功就 commit、發生例外就 rollback
  with psycopg.connect(databaseUrl, row_factory=dict_row) as conn:
    yield conn


def ensureExtensions(databaseUrl: str) -> None:
  # 擴充是整個資料庫共用的，要裝在 public；裝進會被刪掉的暫時 schema，測試結束就一起消失
  with psycopg.connect(databaseUrl, autocommit=True) as conn:
    conn.execute("CREATE EXTENSION IF NOT EXISTS btree_gist SCHEMA public")


@contextmanager
def temporarySchema(databaseUrl: str, prefix: str):
  """建立一個用完就刪的 schema，回傳只看得到它（加上 public）的連線字串，給測試用。"""
  schemaName = f"{prefix}_{uuid.uuid4().hex[:8]}"
  identifier = sql.Identifier(schemaName)
  with psycopg.connect(databaseUrl, autocommit=True) as conn:
    conn.execute(sql.SQL("CREATE SCHEMA {}").format(identifier))
  try:
    # public 要留在 search_path：btree_gist 的運算子類別裝在 public，排除限制要用到
    yield make_conninfo(databaseUrl, options=f"-c search_path={schemaName},public")
  finally:
    with psycopg.connect(databaseUrl, autocommit=True) as conn:
      conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(identifier))


@contextmanager
def mapDbErrors(conn):
  """把資料庫限制錯誤轉成 AppError。包在 savepoint 裡：失敗只回復這一段，同一條連線之後還能繼續用。"""
  try:
    with conn.transaction():
      yield
  except psycopg.errors.UniqueViolation as error:
    raise AppError("DUPLICATE", "資料重複：名稱或編號已經被使用", 409, {"constraint": error.diag.constraint_name})
  except (psycopg.errors.CheckViolation, psycopg.errors.NotNullViolation) as error:
    raise AppError("VALIDATION", "欄位內容不符合規則", 422, {"constraint": error.diag.constraint_name})
  except psycopg.errors.ForeignKeyViolation as error:
    raise AppError("VALIDATION", "參照的資料不存在或仍被使用", 422, {"constraint": error.diag.constraint_name})
