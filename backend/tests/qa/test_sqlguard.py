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
