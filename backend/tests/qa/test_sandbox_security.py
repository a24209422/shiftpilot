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


def testSessionSettingsAreRevertedBetweenQueries(sandbox):
  # 繞過 validateSql，直接呼叫 runQuery：沙盒自己也要守得住
  runQuery(sandbox.conn, "SELECT set_config('default_transaction_read_only', 'off', false), set_config('statement_timeout', '0', false)")
  with pytest.raises(psycopg.Error):
    runQuery(sandbox.conn, "SELECT lo_create(0)")
  # 唯讀還原後連 GRANT 都不能執行；INSERT 也一樣失敗
  with pytest.raises(psycopg.Error):
    sandbox.conn.execute("GRANT INSERT ON pg_temp.leave_requests TO qa_sandbox")
  with pytest.raises(psycopg.Error):
    sandbox.conn.execute("INSERT INTO leave_requests (id) VALUES (1)")
  with pytest.raises(psycopg.errors.QueryCanceled):
    runQuery(sandbox.conn, "SELECT pg_sleep(6.5)")


def testCrossJoinIsCappedInDatabase(sandbox):
  columns, rows, truncated = runQuery(
    sandbox.conn, "SELECT a.day, b.day AS other FROM day_shifts a CROSS JOIN day_shifts b CROSS JOIN day_shifts c"
  )
  assert len(rows) == 200 and truncated is True


def testLargeResultIsCappedBySize(sandbox):
  # 繞過 validateSql（lpad 會被它擋）：就算檢查被繞過，回到應用程式的資料量也有上限
  columns, rows, truncated = runQuery(sandbox.conn, "SELECT lpad('x', 100000) AS s FROM generate_series(1, 50)")
  assert truncated is True and 0 < len(rows) < 50
  assert sum(len(row[0]) for row in rows) <= 1_000_000


def testOtherAskersQueriesAreNotVisible(sandbox, qaSandboxUrl, migratedUrl):
  marker = "marker_9f3c1d_secret"
  with openDb(migratedUrl) as conn:
    data = collectSandboxData(conn, SimpleNamespace(role="admin", employeeId=None, userId=None), date(2026, 11, 21))
  with openSandbox(qaSandboxUrl, data) as other:
    runQuery(other, f"SELECT '{marker}' AS x")
    seen = runQuery(sandbox.conn, "SELECT query FROM pg_stat_activity")[1]
    assert not any(marker in str(row[0]) for row in seen)
    inserted = runQuery(sandbox.conn, "SELECT coalesce(sum(n_tup_ins), 0) FROM pg_stat_all_tables WHERE relname = 'leave_requests' AND schemaname LIKE 'pg_temp%'")[1]
    assert inserted[0][0] == 0


def testJsonValuesAreNestedAndBinarySafe(sandbox):
  rows = runQuery(sandbox.conn, "SELECT array_agg(day), 'a'::bytea, gen_random_uuid() FROM calendar_days WHERE false")[1]
  assert rows[0][0] is None
  rows = runQuery(sandbox.conn, "SELECT array_agg(d), 'a'::bytea, gen_random_uuid() FROM (SELECT current_date AS d) t")[1]
  assert isinstance(rows[0][0][0], str) and rows[0][1] == "61" and isinstance(rows[0][2], str)


def testPublicTablesAreNotGranted(sandbox):
  tables = runQuery(sandbox.conn, "SELECT c.relname FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'v', 'p')")[1]
  for (name,) in tables:
    assert runQuery(sandbox.conn, f"SELECT has_table_privilege('qa_sandbox', 'public.{name}', 'SELECT')")[1] == [[False]]
