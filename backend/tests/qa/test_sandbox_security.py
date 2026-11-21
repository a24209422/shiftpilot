import time
from datetime import date
from types import SimpleNamespace

import psycopg
import pytest

from app.infra.db import openDb
from app.modules.qa.sandbox import collectSandboxData, openSandbox, runQuery
from tests.leave.world import makeWorld


@pytest.fixture
def sandbox(migratedUrl, qaSandboxUrl):
  w = makeWorld(migratedUrl)
  with openDb(migratedUrl) as conn:
    data = collectSandboxData(conn, w.bobActor, date(2026, 11, 21))
    # 測試的真實資料表放在每個測試自己的 schema 裡
    schema = conn.execute("SELECT current_schema() AS name").fetchone()["name"]
  with openSandbox(qaSandboxUrl, data) as conn:
    yield SimpleNamespace(conn=conn, schema=schema)


def expectDenied(conn, sql):
  with pytest.raises(psycopg.Error):
    conn.execute(sql).fetchall()


def testSandboxTablesAreQueryable(sandbox):
  columns, rows, truncated = runQuery(sandbox.conn, "SELECT count(*) AS n FROM employees")
  assert columns == ["n"] and rows == [[4]] and truncated is False


@pytest.mark.parametrize("table", ["users", "sessions", "audit_log", "employees", "leave_requests", "shift_overrides"])
def testRealTablesAreUnreadable(sandbox, table):
  expectDenied(sandbox.conn, f"SELECT * FROM {sandbox.schema}.{table}")


@pytest.mark.parametrize("sql", [
  "SELECT set_config('role', 'schedule_app', false)",
  "SELECT set_config('role', 'postgres', false)",
  "SET ROLE schedule_app",
  "SET SESSION AUTHORIZATION schedule_app",
])
def testCannotSwitchRole(sandbox, sql):
  expectDenied(sandbox.conn, sql)
  assert sandbox.conn.execute("SELECT current_user").fetchone()[0] == "qa_sandbox"


@pytest.mark.parametrize("sql", [
  "SELECT pg_read_file('postgresql.conf')",
  "SELECT pg_ls_dir('.')",
  "SELECT lo_import('/etc/passwd')",
])
def testServerFilesAndLargeObjectsDenied(sandbox, sql):
  expectDenied(sandbox.conn, sql)


@pytest.mark.parametrize("sql", [
  # 唯讀交易仍允許寫暫存表，所以 openSandbox 另外收回自己對暫存表的寫入權限
  "INSERT INTO departments (id, name) VALUES (99, '駭客部')",
  "UPDATE leave_requests SET leave_type = '事假'",
  "DELETE FROM employees",
  "CREATE TEMP TABLE extra (a int)",
  "GRANT INSERT ON departments TO qa_sandbox",
  # lo_create 本來開放給所有人，只有唯讀能擋：用來確認 SELECT 裡呼叫會寫入的函式也會失敗
  "SELECT lo_create(0)",
])
def testSandboxIsReadOnly(sandbox, sql):
  expectDenied(sandbox.conn, sql)
  assert runQuery(sandbox.conn, "SELECT count(*) FROM departments WHERE id = 99")[1] == [[0]]
  assert runQuery(sandbox.conn, "SELECT count(*) FROM employees")[1] == [[4]]


def testRealTablesAreNotWritable(sandbox):
  expectDenied(sandbox.conn, f"INSERT INTO {sandbox.schema}.departments (name) VALUES ('駭客部')")


def testStatementTimeout(sandbox):
  started = time.monotonic()
  with pytest.raises(psycopg.errors.QueryCanceled):
    sandbox.conn.execute("SELECT pg_sleep(10)")
  assert time.monotonic() - started < 8


def testRowsAreCappedAndJsonFriendly(sandbox):
  columns, rows, truncated = runQuery(sandbox.conn, "SELECT day, start_at FROM day_shifts ORDER BY employee_id, day")
  assert len(rows) == 200 and truncated is True
  assert isinstance(rows[0][0], str) and len(rows[0][0]) == 10
