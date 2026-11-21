import pytest

from app.modules.qa.sqlguard import UnsafeSqlError, extractSql, validateSql


def testExtractFromFencedBlock():
  assert extractSql("說明\n```sql\nSELECT 1\n```\n結尾") == "SELECT 1"


def testExtractDropsThinkBlockAndLeadingText():
  assert extractSql("<think>想一下</think>好的，查詢如下 SELECT name FROM employees; 解釋") == "SELECT name FROM employees"


def testExtractKeepsOnlyFirstStatement():
  assert extractSql("SELECT 1; DROP TABLE employees") == "SELECT 1"


@pytest.mark.parametrize("sql", [
  "SELECT name FROM employees",
  "with t AS (SELECT 1 AS a) SELECT a FROM t",
  "SELECT e.name FROM employees e WHERE e.name LIKE '%小美%' ORDER BY e.name OFFSET 0",
])
def testValidAccepted(sql):
  validateSql(sql)


@pytest.mark.parametrize("sql", [
  "",
  "DELETE FROM employees",
  "SELECT 1; SELECT 2",
  "WITH x AS (DELETE FROM employees RETURNING *) SELECT * FROM x",
  "SELECT set_config('role', 'schedule_app', false)",
  "SELECT SET_CONFIG ('role', 'x', false)",
  "SELECT pg_read_file('postgresql.conf')",
  "SELECT pg_ls_dir('.')",
  "SELECT lo_import('/etc/passwd')",
  "SELECT * FROM dblink('host=x', 'select 1') AS t(a int)",
  "SET ROLE schedule_app",
  "RESET ROLE",
  "COPY employees TO STDOUT",
  "DO $$ BEGIN END $$",
  "SELECT * FROM employees FOR UPDATE",
  "CALL something()",
])
def testUnsafeRejected(sql):
  with pytest.raises(UnsafeSqlError):
    validateSql(sql)


# 以下為第二輪修正新增的測試：註解、引號識別字、字串常值、缺漏的關鍵字與函式

@pytest.mark.parametrize("sql", [
  "SELECT set_config/**/('role','x',false)",
  'SELECT "set_config"(\'a\',\'b\',false)',
  "SELECT pg_catalog.\"pg_read_file\"('x')",
  "SELECT \"delete\" FROM employees",
  "SELECT 1 INTO newtable FROM employees",
  "SELECT * FROM employees FOR NO KEY UPDATE",
  "SELECT * FROM employees FOR SHARE",
  "SELECT * FROM employees FOR KEY SHARE",
  "SELECT setval('seq', 1)",
  "SELECT nextval('seq')",
  "SELECT currval('seq')",
  "SELECT pg_notify('ch', 'msg')",
  "SELECT pg_sleep(10)",
  "SELECT pg_advisory_lock(1)",
  "SELECT query_to_xml('select 1', true, true, '')",
  "SELECT lo_from_bytea(0, 'x')",
  "SELECT 'x' AS a, $tag$ select 1 $tag$",
  "SELECT $$x$$",
  "SELECT E'a\'b'",
  "SELECT e'x'",
  "SELECT 1 /* ; */ ; DELETE FROM employees",
  "SELECT 1 -- 註解\nDELETE FROM employees",
])
def testUnsafeRejectedAfterCleaning(sql):
  with pytest.raises(UnsafeSqlError):
    validateSql(sql)


@pytest.mark.parametrize("sql", [
  "SELECT * FROM logs WHERE source='import'",
  "SELECT name FROM employees WHERE reason LIKE '%do%'",
  "SELECT name FROM employees WHERE note LIKE '%;%'",
  "SELECT name FROM employees WHERE name = 'O''Brien delete'",
  "SELECT name FROM employees WHERE memo = '-- drop'",
  "SELECT name FROM employees /* 註解 */ WHERE id = 1",
  "SELECT created_at, comment_count FROM posts",
  "SELECT name FROM employees WHERE name = 'a\'",
])
def testFalsePositivesAccepted(sql):
  validateSql(sql)


def testExtractWorksRightAfterCjkText():
  assert extractSql("查詢如下SELECT 1") == "SELECT 1"


def testExtractDropsClosedThinkBeforeSql():
  assert extractSql("<think>推理</think>SELECT 1") == "SELECT 1"


def testExtractDropsUnclosedThinkBlock():
  assert extractSql("<think>想一下 SELECT 1") == ""
