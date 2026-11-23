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
  "SELECT pg_sleep_for('1 hour')",
  "SELECT pg_sleep_until(now() + interval '1 hour')",
  "SELECT * FROM ts_stat('SELECT to_tsvector(set_config(''statement_timeout'',''0'',false))')",
  "SELECT ts_rewrite(to_tsquery('a'), 'SELECT 1, 2')",
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


# 第三輪：U&"..." / U&'...' 會解碼 Unicode 跳脫，以及補上的 XML 與 pg_ls_ 函式

@pytest.mark.parametrize("sql", [
  "SELECT U&\"pg\005fread\005ffile\"('x')",
  "SELECT U&\"\0073et\005fconfig\"('role','x',false)",
  "SELECT U&'abc'",
  "SELECT u&'abc'",
  "SELECT pg_ls_waldir()",
  "SELECT table_to_xml('employees', true, true, '')",
  "SELECT cursor_to_xml('c', true, true, '')",
  "SELECT database_to_xml(true, true, '')",
  "SELECT schema_to_xml('public', true, true, '')",
])
def testUnicodeEscapeAndXmlFunctionsRejected(sql):
  with pytest.raises(UnsafeSqlError):
    validateSql(sql)


def testUnicodeAmpersandInsideStringAccepted():
  validateSql("SELECT name FROM employees WHERE note = 'U&\"x\"'")


# 第四輪：PostgreSQL 的 -- 註解遇到 \r 也會結束；pg_try_advisory_* 的 advisory 前面是底線，\b 擋不到

@pytest.mark.parametrize("sql", [
  "SELECT 1 --x\rUNION SELECT pg_terminate_backend(pid) FROM pg_stat_activity",
  "SELECT 1 --x\rUNION SELECT 1 FROM employees; DELETE FROM employees",
  "SELECT pg_try_advisory_lock(7301)",
  "SELECT pg_try_advisory_xact_lock(7301)",
  "SELECT pg_try_advisory_lock_shared(7301)",
  "SELECT pg_catalog.pg_try_advisory_lock(k) FROM generate_series(1, 10000) k",
])
def testCarriageReturnCommentAndTryAdvisoryRejected(sql):
  with pytest.raises(UnsafeSqlError):
    validateSql(sql)


def testCrlfLineCommentAccepted():
  # Windows 換行的註解仍然要能正常查詢
  validateSql("SELECT name -- 姓名\r\nFROM employees")


# 第五輪：會把結果放大到幾百 MB 的函式；程式碼區塊的語言標籤；說明文字裡的 with

@pytest.mark.parametrize("sql", [
  "SELECT repeat('x', 500000000)",
  "SELECT lpad('x', 500000000)",
  "SELECT RPAD('x', 500000000, 'y')",
  "SELECT array_fill(1, ARRAY[100000000])",
  "SELECT pg_catalog.repeat('x', 10)",
])
def testAmplifyingFunctionsRejected(sql):
  with pytest.raises(UnsafeSqlError):
    validateSql(sql)


def testColumnNamedLikeAmplifierInsideStringAccepted():
  validateSql("SELECT name FROM employees WHERE note = 'repeat'")


@pytest.mark.parametrize("fence", ["sql", "SQL", "postgresql", "pgsql", "postgres", ""])
def testExtractIgnoresFenceLanguageTag(fence):
  assert extractSql(f"說明\n```{fence}\nSELECT 1\n```") == "SELECT 1"


@pytest.mark.parametrize("text,expected", [
  ("Here is the query with a join: SELECT e.name FROM employees e", "SELECT e.name FROM employees e"),
  ("說明 WITH t AS (SELECT 1 AS a) SELECT a FROM t", "WITH t AS (SELECT 1 AS a) SELECT a FROM t"),
  ("WITH RECURSIVE t(n) AS (SELECT 1) SELECT n FROM t", "WITH RECURSIVE t(n) AS (SELECT 1) SELECT n FROM t"),
  ("with x as materialized (select 1) select * from x", "with x as materialized (select 1) select * from x"),
  ("查詢：with t AS(SELECT 1) SELECT * FROM t", "with t AS(SELECT 1) SELECT * FROM t"),
])
def testExtractStartsAtRealCte(text, expected):
  assert extractSql(text) == expected
