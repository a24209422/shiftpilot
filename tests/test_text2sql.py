import sqlite3
from datetime import date, datetime

import pytest

import db
import text2sql

fixedNow = datetime(2026, 11, 17, 14, 30)  # 星期二


@pytest.fixture
def dbPath(tmp_path):
  path = tmp_path / "test.db"
  db.initDb(path)
  db.seedDemoData(path, today=fixedNow.date())
  return path


def makeFakeLlm(replies):
  calls = []

  def fakeLlm(messages):
    calls.append(messages)
    return replies[len(calls) - 1]

  fakeLlm.calls = calls
  return fakeLlm


def testExtractSqlFromCodeFence():
  reply = "好的：\n```sql\nSELECT * FROM events;\n```"
  assert text2sql.extractSql(reply) == "SELECT * FROM events"


def testExtractSqlIgnoresThinkBlockAndTrailingExplanation():
  reply = "<think>想一下 select 什麼</think>以下是查詢：\nSELECT title FROM events; 這會列出所有標題"
  assert text2sql.extractSql(reply) == "SELECT title FROM events"


def testExtractSqlKeepsOnlyFirstStatement():
  assert text2sql.extractSql("SELECT 1; DROP TABLE events") == "SELECT 1"


@pytest.mark.parametrize("sql", [
  "SELECT * FROM events",
  "WITH x AS (SELECT * FROM events) SELECT COUNT(*) FROM x",
  "select title from events where note like '%x%'",
])
def testValidateSqlAllowsReadOnlyQueries(sql):
  text2sql.validateSql(sql)


@pytest.mark.parametrize("sql", [
  "",
  "DELETE FROM events",
  "SELECT 1; DROP TABLE events",
  "WITH x AS (SELECT 1) DELETE FROM events",
  "SELECT * FROM events WHERE id IN (SELECT 1) UNION SELECT 1 FROM pragma_table_info('events'); PRAGMA x",
])
def testValidateSqlRejectsWritesAndMultipleStatements(sql):
  with pytest.raises(text2sql.UnsafeSqlError):
    text2sql.validateSql(sql)


def testReadOnlyConnectionBlocksWritesEvenWithoutValidation(dbPath):
  with pytest.raises(sqlite3.OperationalError):
    db.runReadOnlyQuery(dbPath, "DELETE FROM events")
  assert db.runReadOnlyQuery(dbPath, "SELECT COUNT(*) FROM events")[1][0][0] > 0


def testPromptContainsDatesSchemaAndVocabulary(dbPath):
  messages = text2sql.buildMessages("問題", db.getLlmSchemaText(), db.getVocabulary(dbPath), fixedNow)
  systemPrompt = messages[0]["content"]

  assert "2026-11-18 星期三（明天）" in systemPrompt
  assert "下週：2026-11-23 ～ 2026-11-29" in systemPrompt
  assert "CREATE TABLE event_details" in systemPrompt
  assert "王小明" in systemPrompt
  assert messages[-1] == {"role": "user", "content": "問題"}


def getFewShotSqls(dbPath):
  messages = text2sql.buildMessages("問題", db.getLlmSchemaText(), db.getVocabulary(dbPath), fixedNow)
  return [text2sql.extractSql(message["content"]) for message in messages[1:-1] if message["role"] == "assistant"]


def testPromptTeachesModelToQueryTheFlatView(dbPath):
  messages = text2sql.buildMessages("問題", db.getLlmSchemaText(), db.getVocabulary(dbPath), fixedNow)
  systemPrompt = messages[0]["content"]
  fewShotSqls = getFewShotSqls(dbPath)

  # 一筆排程在 view 裡有多列，prompt 沒提醒的話模型會用 COUNT(*) 多算
  assert "COUNT(DISTINCT event_id)" in systemPrompt
  assert "event_resources" not in systemPrompt
  assert len(fewShotSqls) >= 2
  assert all("event_details" in sql and "JOIN" not in sql for sql in fewShotSqls)


def testFewShotExamplesRunOnTheRealSchema(dbPath):
  # 範例 SQL 如果用到不存在的欄位，等於在教模型寫錯
  for sql in getFewShotSqls(dbPath):
    text2sql.validateSql(sql)
    db.runReadOnlyQuery(dbPath, sql)


def testAnswerQuestionRunsGeneratedSql(dbPath):
  fakeLlm = makeFakeLlm(["```sql\nSELECT title FROM events WHERE category = 'shift' ORDER BY start_at\n```"])

  result = text2sql.answerQuestion("有哪些班？", dbPath, now=fixedNow, llm=fakeLlm)

  assert result["error"] is None
  assert result["columns"] == ["title"]
  assert {row[0] for row in result["rows"]} == {"早班", "晚班"}
  assert result["attempts"] == 1


def testAnswerQuestionFeedsErrorBackAndRetries(dbPath):
  fakeLlm = makeFakeLlm([
    "SELECT wrong_column FROM events",
    "SELECT COUNT(*) FROM events",
  ])

  result = text2sql.answerQuestion("幾筆？", dbPath, now=fixedNow, llm=fakeLlm)

  assert result["error"] is None
  assert result["attempts"] == 2
  assert "wrong_column" in fakeLlm.calls[1][-1]["content"]


def testAnswerQuestionGivesUpAfterMaxRetries(dbPath):
  fakeLlm = makeFakeLlm(["DELETE FROM events", "DELETE FROM events"])

  result = text2sql.answerQuestion("刪掉", dbPath, now=fixedNow, llm=fakeLlm)

  assert result["error"] is not None
  assert result["rows"] == []
  assert len(db.listEvents(dbPath, date(2026, 1, 1), date(2026, 12, 31))) > 0
