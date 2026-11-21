from datetime import datetime

import pytest

from app.infra.db import openDb
from app.infra.errors import AppError
from app.modules.qa import service
from app.modules.qa.llm import LlmUnavailableError
from tests.leave.world import makeWorld

now = datetime(2026, 11, 21, 10)


@pytest.fixture(autouse=True)
def localModelsOnly(monkeypatch):
  monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:3b")
  for name in ("LOCAL_MODELS", "OPENROUTER_API_KEY", "GOOGLE_AI_API_KEY"):
    monkeypatch.setenv(name, "")


@pytest.fixture
def world(migratedUrl, qaSandboxUrl):
  w = makeWorld(migratedUrl)
  w.qaUrl = qaSandboxUrl
  return w


def scripted(*replies):
  calls = []

  def fake(model, messages):
    calls.append(messages)
    reply = replies[len(calls) - 1]
    if isinstance(reply, Exception):
      raise reply
    return reply

  fake.calls = calls
  return fake


def ask(w, llm, question="有哪些員工？", qaUrl="default", model="qwen2.5:3b"):
  with openDb(w.url) as conn:
    return service.ask(conn, w.bobActor, question, model, w.qaUrl if qaUrl == "default" else qaUrl, now, llm=llm)


def expectError(code, call, *args, **kwargs):
  with pytest.raises(AppError) as info:
    call(*args, **kwargs)
  assert info.value.code == code
  return info.value


def testSuccessReturnsAnswerTableAndWindow(world):
  llm = scripted("```sql\nSELECT name FROM employees ORDER BY name\n```", "目前有四位員工。")
  result = ask(world, llm)
  assert result["answer"] == "目前有四位員工。"
  assert result["sql"] == "SELECT name FROM employees ORDER BY name"
  assert result["columns"] == ["name"] and len(result["rows"]) == 4 and result["truncated"] is False
  assert result["model"] == "qwen2.5:3b" and result["remote"] is False
  assert result["window"] == {"from": "2026-08-23", "to": "2027-02-19"}
  # 回答句那次呼叫看得到問題與查詢結果
  assert "有哪些員工？" in llm.calls[1][-1]["content"] and "alice" in llm.calls[1][-1]["content"]


def testSqlErrorIsFedBackAndRetried(world):
  llm = scripted("SELECT nope FROM employees", "SELECT name FROM employees", "四位。")
  result = ask(world, llm)
  assert result["sql"] == "SELECT name FROM employees"
  assert "這句 SQL 失敗了" in llm.calls[1][-1]["content"]


def testUnsafeSqlIsRetried(world):
  llm = scripted("SELECT set_config('role', 'schedule_app', false)", "SELECT count(*) FROM employees", "四位。")
  assert ask(world, llm)["rows"] == [[4]]


def testFailsAfterOneRetry(world):
  error = expectError("QA_QUERY_FAILED", ask, world, scripted("SELECT nope FROM employees", "SELECT still_nope FROM employees"))
  assert error.status == 422 and error.details["sql"] == "SELECT still_nope FROM employees" and error.details["error"]


def testModelUnavailable(world):
  error = expectError("QA_MODEL_UNAVAILABLE", ask, world, scripted(LlmUnavailableError("無法呼叫 Ollama：refused")))
  assert error.status == 503 and "Ollama" in error.message


def testAnswerFallsBackWhenSecondCallFails(world):
  result = ask(world, scripted("SELECT name FROM employees", LlmUnavailableError("timeout")))
  assert result["answer"] == "查到 4 筆資料。"


def testEmptyResultAnswerStillComesFromModel(world):
  result = ask(world, scripted("SELECT name FROM employees WHERE name = 'nobody'", "查無資料。"))
  assert result["rows"] == [] and result["answer"] == "查無資料。"


def testNotConfigured(world):
  assert expectError("QA_NOT_CONFIGURED", ask, world, scripted(), qaUrl=None).status == 503


def testUnknownModel(world):
  expectError("QA_UNKNOWN_MODEL", ask, world, scripted(), model="gpt-x")


@pytest.mark.parametrize("question", ["", "   ", "問" * 301])
def testQuestionLength(world, question):
  expectError("VALIDATION", ask, world, scripted(), question=question)


def testPromptMentionsWindowVocabularyAndDates(world):
  llm = scripted("SELECT 1", "好。")
  ask(world, llm)
  system = llm.calls[0][0]["content"]
  assert "2026-08-23" in system and "2027-02-19" in system
  assert "工程部" in system and "標準班" in system and "事假" in system
  assert "2026-11-22 星期日（明天）" in system
