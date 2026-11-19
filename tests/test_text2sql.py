from datetime import date, datetime

import psycopg
import pytest

import db
import text2sql

fixedNow = datetime(2026, 11, 17, 14, 30)  # 星期二


@pytest.fixture
def demoDatabaseUrl(databaseUrl):
  db.seedDemoData(databaseUrl, today=fixedNow.date())
  return databaseUrl


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
  "WITH removed AS (DELETE FROM events RETURNING *) SELECT * FROM removed",
  "SELECT * FROM events WHERE id IN (SELECT 1) UNION SELECT 1 FROM events; TRUNCATE events",
])
def testValidateSqlRejectsWritesAndMultipleStatements(sql):
  with pytest.raises(text2sql.UnsafeSqlError):
    text2sql.validateSql(sql)


def testReadOnlyConnectionBlocksWritesEvenWithoutValidation(demoDatabaseUrl):
  with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
    db.runReadOnlyQuery(demoDatabaseUrl, "DELETE FROM events")
  assert db.runReadOnlyQuery(demoDatabaseUrl, "SELECT COUNT(*) FROM events")[1][0][0] > 0


def testPromptContainsDatesSchemaAndVocabulary(demoDatabaseUrl):
  messages = text2sql.buildMessages("問題", db.getLlmSchemaText(), db.getVocabulary(demoDatabaseUrl), fixedNow)
  systemPrompt = messages[0]["content"]

  assert "2026-11-18 星期三（明天）" in systemPrompt
  assert "下週：2026-11-23 ～ 2026-11-29" in systemPrompt
  # 「下一個行程」要跟現在比較，模型需要日期加時間的完整字串才寫得出 start_at > '...'
  assert "start_at > '2026-11-17 14:30'" in systemPrompt
  assert "CREATE TABLE event_details" in systemPrompt
  assert "王小明" in systemPrompt
  assert messages[-1] == {"role": "user", "content": "問題"}


def getFewShotSqls(demoDatabaseUrl):
  messages = text2sql.buildMessages("問題", db.getLlmSchemaText(), db.getVocabulary(demoDatabaseUrl), fixedNow)
  return [text2sql.extractSql(message["content"]) for message in messages[1:-1] if message["role"] == "assistant"]


def testPromptTeachesModelToQueryTheFlatView(demoDatabaseUrl):
  messages = text2sql.buildMessages("問題", db.getLlmSchemaText(), db.getVocabulary(demoDatabaseUrl), fixedNow)
  systemPrompt = messages[0]["content"]
  fewShotSqls = getFewShotSqls(demoDatabaseUrl)

  # 一筆排程在 view 裡有多列，prompt 沒提醒的話模型會用 COUNT(*) 多算
  assert "COUNT(DISTINCT event_id)" in systemPrompt
  assert "event_resources" not in systemPrompt
  assert len(fewShotSqls) >= 2
  assert all("event_details" in sql and "JOIN" not in sql for sql in fewShotSqls)


def testFewShotExamplesRunOnTheRealSchema(demoDatabaseUrl):
  # 範例 SQL 如果用到不存在的欄位，等於在教模型寫錯
  for sql in getFewShotSqls(demoDatabaseUrl):
    text2sql.validateSql(sql)
    db.runReadOnlyQuery(demoDatabaseUrl, sql)


def testAnswerQuestionRunsGeneratedSql(demoDatabaseUrl):
  fakeLlm = makeFakeLlm(["```sql\nSELECT title FROM events WHERE category = 'shift' ORDER BY start_at\n```"])

  result = text2sql.answerQuestion("有哪些班？", demoDatabaseUrl, now=fixedNow, llm=fakeLlm)

  assert result["error"] is None
  assert result["columns"] == ["title"]
  assert {row[0] for row in result["rows"]} == {"早班", "晚班"}
  assert result["attempts"] == 1


def testAnswerQuestionFeedsErrorBackAndRetries(demoDatabaseUrl):
  fakeLlm = makeFakeLlm([
    "SELECT wrong_column FROM events",
    "SELECT COUNT(*) FROM events",
  ])

  result = text2sql.answerQuestion("幾筆？", demoDatabaseUrl, now=fixedNow, llm=fakeLlm)

  assert result["error"] is None
  assert result["attempts"] == 2
  assert "wrong_column" in fakeLlm.calls[1][-1]["content"]


def testAnswerQuestionGivesUpAfterMaxRetries(demoDatabaseUrl):
  fakeLlm = makeFakeLlm(["DELETE FROM events", "DELETE FROM events"])

  result = text2sql.answerQuestion("刪掉", demoDatabaseUrl, now=fixedNow, llm=fakeLlm)

  assert result["error"] is not None
  assert result["rows"] == []
  assert len(db.listEvents(demoDatabaseUrl, date(2026, 1, 1), date(2026, 12, 31))) > 0


cloudModels = "anthropic/claude-haiku-5.5,openai/gpt-6-luna"


class FakeResponse:
  def __init__(self, payload):
    self.payload = payload

  def raise_for_status(self):
    pass

  def json(self):
    return self.payload


def makeFakePost(content):
  calls = []

  def fakePost(url, **kwargs):
    calls.append({"url": url, **kwargs})
    # 照 OpenRouter 實際回傳的結構，不只放程式會讀的欄位
    return FakeResponse({
      "id": "gen-1",
      "model": kwargs["json"]["model"],
      "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
      "usage": {"prompt_tokens": 2000, "completion_tokens": 20, "total_tokens": 2020},
    })

  fakePost.calls = calls
  return fakePost


def testParseModelListIgnoresSpacesAndEmptyItems():
  assert text2sql.parseModelList(" qwen2.5:3b, ,qwen3-vl:4b-instruct,") == ["qwen2.5:3b", "qwen3-vl:4b-instruct"]
  assert text2sql.parseModelList("") == []
  assert text2sql.parseModelList(None) == []


def testListModelsHidesCloudModelsWithoutApiKey(modelEnv):
  modelEnv(OLLAMA_MODEL="qwen2.5:3b", OLLAMA_MODELS="qwen2.5:3b,qwen3-vl:4b-instruct",
           OPENROUTER_API_KEY="   ", OPENROUTER_MODELS=cloudModels)
  assert text2sql.listModels() == ["qwen2.5:3b", "qwen3-vl:4b-instruct"]


def testListModelsAddsCloudModelsWhenApiKeySet(modelEnv):
  modelEnv(OLLAMA_MODEL="qwen2.5:3b", OLLAMA_MODELS="qwen2.5:3b,qwen3-vl:4b-instruct",
           OPENROUTER_API_KEY="test-key", OPENROUTER_MODELS=cloudModels)
  assert text2sql.listModels() == [
    "qwen2.5:3b", "qwen3-vl:4b-instruct", "anthropic/claude-haiku-5.5", "openai/gpt-6-luna",
  ]


def testListModelsPutsDefaultModelFirstWhenMissingFromList(modelEnv):
  modelEnv(OLLAMA_MODEL="llama3:8b", OLLAMA_MODELS="qwen2.5:3b,qwen2.5:3b")
  assert text2sql.listModels() == ["llama3:8b", "qwen2.5:3b"]


def testListModelsFallsBackToDefaultModel(modelEnv):
  assert text2sql.listModels() == ["qwen2.5:3b"]


def testGetProviderUsesOpenRouterListOnly(modelEnv):
  modelEnv(OPENROUTER_MODELS="anthropic/claude-haiku-5.5")
  assert text2sql.getProvider("anthropic/claude-haiku-5.5") == "openrouter"
  # Ollama 的模型名稱也可能有斜線，不在清單裡就是本機模型
  assert text2sql.getProvider("hf.co/someone/model") == "ollama"
  assert text2sql.getProvider("openai/gpt-6-luna") == "ollama"


def testGetLlmRoutesByProvider(modelEnv):
  modelEnv(OPENROUTER_MODELS=cloudModels)
  cloudLlm = text2sql.getLlm("openai/gpt-6-luna")
  localLlm = text2sql.getLlm("qwen2.5:3b")
  assert cloudLlm.func is text2sql.callOpenRouter
  assert cloudLlm.keywords == {"model": "openai/gpt-6-luna"}
  assert localLlm.func is text2sql.callOllama
  assert localLlm.keywords == {"model": "qwen2.5:3b"}


def testCallOpenRouterSendsChatRequest(monkeypatch, modelEnv):
  modelEnv(OPENROUTER_API_KEY="test-key")
  fakePost = makeFakePost("```sql\nSELECT 1\n```")
  monkeypatch.setattr(text2sql.requests, "post", fakePost)
  messages = [{"role": "user", "content": "問題"}]

  reply = text2sql.callOpenRouter(messages, model="openai/gpt-6-luna")

  call = fakePost.calls[0]
  assert reply == "```sql\nSELECT 1\n```"
  assert call["url"] == "https://openrouter.ai/api/v1/chat/completions"
  assert call["headers"] == {"Authorization": "Bearer test-key"}
  assert call["json"] == {"model": "openai/gpt-6-luna", "messages": messages, "temperature": 0}
  assert call["timeout"] == 60


def testCallOpenRouterTreatsNullContentAsEmpty(monkeypatch, modelEnv):
  modelEnv(OPENROUTER_API_KEY="test-key")
  monkeypatch.setattr(text2sql.requests, "post", makeFakePost(None))
  assert text2sql.callOpenRouter([{"role": "user", "content": "問題"}], model="openai/gpt-6-luna") == ""
