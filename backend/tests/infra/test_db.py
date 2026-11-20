import psycopg
import pytest

from app.infra.db import ensureExtensions, mapDbErrors, openDb, temporarySchema


def testTemporarySchemaIsolatesTables(testDatabaseUrl):
  with temporarySchema(testDatabaseUrl, "test") as urlA, temporarySchema(testDatabaseUrl, "test") as urlB:
    for url, value in ((urlA, 1), (urlB, 2)):
      with openDb(url) as conn:
        conn.execute("CREATE TABLE t (n int)")
        conn.execute("INSERT INTO t VALUES (%s)", (value,))
    with openDb(urlA) as conn:
      assert [row["n"] for row in conn.execute("SELECT n FROM t").fetchall()] == [1]
    with openDb(urlB) as conn:
      assert [row["n"] for row in conn.execute("SELECT n FROM t").fetchall()] == [2]


def testTemporarySchemaIsDroppedOnExit(testDatabaseUrl):
  with temporarySchema(testDatabaseUrl, "test") as url:
    with openDb(url) as conn:
      schemaName = conn.execute("SELECT current_schema() AS s").fetchone()["s"]
  with openDb(testDatabaseUrl) as conn:
    found = conn.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name = %s", (schemaName,)).fetchall()
  assert found == []


def testOpenDbCommitsOnSuccessAndRollsBackOnError(testDatabaseUrl):
  with temporarySchema(testDatabaseUrl, "test") as url:
    with openDb(url) as conn:
      conn.execute("CREATE TABLE t (n int)")
      conn.execute("INSERT INTO t VALUES (1)")
    with pytest.raises(RuntimeError):
      with openDb(url) as conn:
        conn.execute("INSERT INTO t VALUES (2)")
        raise RuntimeError("boom")
    with openDb(url) as conn:
      assert [row["n"] for row in conn.execute("SELECT n FROM t").fetchall()] == [1]


def testBtreeGistIsAvailable(testDatabaseUrl):
  try:
    ensureExtensions(testDatabaseUrl)
    ensureExtensions(testDatabaseUrl)
  except psycopg.errors.InsufficientPrivilege:
    pytest.fail(
      "schedule_app 沒有權限建立 btree_gist，請用管理員帳號建立：\n"
      'docker compose exec postgres psql -U postgres -d schedule_test -c "CREATE EXTENSION IF NOT EXISTS btree_gist SCHEMA public"'
    )
  with openDb(testDatabaseUrl) as conn:
    assert conn.execute("SELECT 1 FROM pg_extension WHERE extname = 'btree_gist'").fetchone() is not None


def testMapDbErrorsAsFirstStatementStaysInsideOuterTransaction(testDatabaseUrl):
  # 連線上的第一個語句如果是 transaction()，psycopg 會開一個自己 commit 的交易而不是 savepoint，
  # 之後請求失敗的 rollback 就救不回已經寫入的資料
  with temporarySchema(testDatabaseUrl, "test") as url:
    with openDb(url) as conn:
      conn.execute("CREATE TABLE t (n int)")
    with pytest.raises(RuntimeError):
      with openDb(url) as conn:
        with mapDbErrors(conn):
          conn.execute("INSERT INTO t VALUES (1)")
        raise RuntimeError("後面的步驟失敗")
    with openDb(url) as conn:
      assert conn.execute("SELECT count(*) AS n FROM t").fetchone()["n"] == 0
