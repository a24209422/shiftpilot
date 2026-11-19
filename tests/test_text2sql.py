import json
from datetime import date, datetime

import psycopg
import pytest
import requests

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
  assert "CREATE TABLE event_resources" in systemPrompt
  assert "- resources.name：" in systemPrompt
  assert "resource_name（resources.name）" not in systemPrompt
  assert "王小明" in systemPrompt
  assert messages[-1] == {"role": "user", "content": "問題"}


def getFewShotSqls(demoDatabaseUrl):
  messages = text2sql.buildMessages("問題", db.getLlmSchemaText(), db.getVocabulary(demoDatabaseUrl), fixedNow)
  return [text2sql.extractSql(message["content"]) for message in messages[1:-1] if message["role"] == "assistant"]


def testPromptTeachesModelToJoinRawTables(demoDatabaseUrl):
  messages = text2sql.buildMessages("問題", db.getLlmSchemaText(), db.getVocabulary(demoDatabaseUrl), fixedNow)
  systemPrompt = messages[0]["content"]
  fewShotSqls = getFewShotSqls(demoDatabaseUrl)

  # JOIN event_resources 之後一筆排程有多列，prompt 沒提醒的話模型會用 COUNT(*) 多算
  assert "COUNT(DISTINCT events.id)" in systemPrompt
  assert "event_details" not in systemPrompt
  assert len(fewShotSqls) == 3
  assert all("event_details" not in sql and "FROM events" in sql for sql in fewShotSqls)


viewVersionFewShotSqls = [
  "SELECT resource_name, title, start_at, end_at FROM event_details "
  "WHERE resource_name LIKE '%小明%' AND start_at::date = '2026-11-18' ORDER BY start_at",
  "SELECT COUNT(DISTINCT event_id) AS meeting_count FROM event_details "
  "WHERE category = 'meeting' AND start_at::date BETWEEN '2026-11-23' AND '2026-11-29'",
  "SELECT title, start_at, end_at FROM event_details WHERE resource_name LIKE '%李小華%' "
  "AND event_id IN (SELECT event_id FROM event_details WHERE resource_name LIKE '%陳大文%') ORDER BY start_at",
]


def testFewShotResultsMatchViewVersion(demoDatabaseUrl):
  # 改寫只換寫法不換意思：每個範例查出來的結果要跟改寫前的 view 版本一模一樣
  for newSql, viewSql in zip(getFewShotSqls(demoDatabaseUrl), viewVersionFewShotSqls, strict=True):
    _, viewRows = db.runReadOnlyQuery(demoDatabaseUrl, viewSql)
    assert viewRows
    assert db.runReadOnlyQuery(demoDatabaseUrl, newSql)[1] == viewRows


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


def makeFakePost(content):
  calls = []

  def fakePost(url, **kwargs):
    calls.append({"url": url, **kwargs})
    # 照 OpenRouter 實際回傳的結構，不只放程式會讀的欄位
    return makeOpenRouterResponse(200, {
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
  modelEnv(OLLAMA_MODEL="qwen2.5:3b", LOCAL_MODELS="qwen2.5:3b,qwen3-vl:4b-instruct",
           OPENROUTER_API_KEY="   ", OPENROUTER_MODELS=cloudModels)
  assert text2sql.listModels() == ["qwen2.5:3b", "qwen3-vl:4b-instruct"]


def testListModelsAddsCloudModelsWhenApiKeySet(modelEnv):
  modelEnv(OLLAMA_MODEL="qwen2.5:3b", LOCAL_MODELS="qwen2.5:3b,qwen3-vl:4b-instruct",
           OPENROUTER_API_KEY="test-key", OPENROUTER_MODELS=cloudModels)
  assert text2sql.listModels() == [
    "qwen2.5:3b", "qwen3-vl:4b-instruct", "anthropic/claude-haiku-5.5", "openai/gpt-6-luna",
  ]


def testListModelsPutsDefaultModelFirstWhenMissingFromList(modelEnv):
  modelEnv(OLLAMA_MODEL="llama3:8b", LOCAL_MODELS="qwen2.5:3b,qwen2.5:3b")
  assert text2sql.listModels() == ["llama3:8b", "qwen2.5:3b"]


def testListModelsIgnoresOllamaStorageDirectory(modelEnv):
  # OLLAMA_MODELS 是 Ollama 自己用來指定模型存放資料夾的環境變數，不能被當成選單清單
  modelEnv(OLLAMA_MODEL="qwen2.5:3b", OLLAMA_MODELS=r"D:\models\ollama", LOCAL_MODELS="qwen2.5:3b,qwen3-vl:4b-instruct")
  assert text2sql.listModels() == ["qwen2.5:3b", "qwen3-vl:4b-instruct"]


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
  assert cloudLlm.func is text2sql.callCloudModel
  assert cloudLlm.keywords == {"provider": "openrouter", "model": "openai/gpt-6-luna"}
  assert localLlm.func is text2sql.callOllama
  assert localLlm.keywords == {"model": "qwen2.5:3b"}


def testCallOpenRouterSendsChatRequest(monkeypatch, modelEnv):
  modelEnv(OPENROUTER_API_KEY="test-key")
  fakePost = makeFakePost("```sql\nSELECT 1\n```")
  monkeypatch.setattr(text2sql.requests, "post", fakePost)
  messages = [{"role": "user", "content": "問題"}]

  reply = text2sql.callCloudModel(messages, provider="openrouter", model="openai/gpt-6-luna")

  call = fakePost.calls[0]
  assert reply == "```sql\nSELECT 1\n```"
  assert call["url"] == "https://openrouter.ai/api/v1/chat/completions"
  assert call["headers"] == {"Authorization": "Bearer test-key"}
  assert call["json"] == {"model": "openai/gpt-6-luna", "messages": messages, "temperature": 0}
  assert call["timeout"] == 60


def testCallOpenRouterTreatsNullContentAsEmpty(monkeypatch, modelEnv):
  modelEnv(OPENROUTER_API_KEY="test-key")
  monkeypatch.setattr(text2sql.requests, "post", makeFakePost(None))
  assert text2sql.callCloudModel([{"role": "user", "content": "問題"}], provider="openrouter", model="openai/gpt-6-luna") == ""


def makeHttpError(statusCode, body):
  response = requests.Response()
  response.status_code = statusCode
  response._content = body.encode("utf-8")
  return requests.HTTPError(f"{statusCode} Error", response=response)


def testDescribeModelMarksCloudAndLocal(modelEnv):
  modelEnv(OPENROUTER_MODELS="openai/gpt-6-luna")
  assert text2sql.describeModel("openai/gpt-6-luna") == "openai/gpt-6-luna（雲端）"
  assert text2sql.describeModel("qwen2.5:3b") == "qwen2.5:3b（本機）"


def testDescribeLlmErrorExplainsOpenRouterAuthAndCredit(modelEnv):
  modelEnv(OPENROUTER_MODELS="openai/gpt-6-luna")
  assert text2sql.describeLlmError(makeHttpError(401, "{}"), "openai/gpt-6-luna") == (
    "無法呼叫 OpenRouter（HTTP 401）：API key 錯誤，請確認 .env 的 OPENROUTER_API_KEY"
  )
  assert text2sql.describeLlmError(makeHttpError(402, "{}"), "openai/gpt-6-luna") == (
    "無法呼叫 OpenRouter（HTTP 402）：OpenRouter 餘額不足"
  )


def testDescribeLlmErrorTruncatesOtherHttpErrors(modelEnv):
  modelEnv(OPENROUTER_MODELS="openai/gpt-6-luna")
  prefix = "無法呼叫 OpenRouter（HTTP 502）："

  message = text2sql.describeLlmError(makeHttpError(502, "<html>" + "x" * 1000), "openai/gpt-6-luna")

  assert message.startswith(prefix + "<html>")
  assert len(message) == len(prefix) + 300


def testDescribeLlmErrorWithoutResponse(modelEnv):
  modelEnv(OPENROUTER_MODELS="openai/gpt-6-luna")
  error = requests.ConnectionError("連不上")
  assert text2sql.describeLlmError(error, "openai/gpt-6-luna") == "無法呼叫 OpenRouter：連不上"


def testDescribeLlmErrorKeepsOllamaHint(modelEnv):
  error = requests.ConnectionError("refused")
  assert text2sql.describeLlmError(error, "qwen2.5:3b") == (
    "無法呼叫 Ollama：refused\n\n請確認 Ollama 已啟動，且已下載 qwen2.5:3b。"
  )


def makeOpenRouterResponse(statusCode, payload):
  response = requests.Response()
  response.status_code = statusCode
  response.encoding = "utf-8"
  response._content = json.dumps(payload).encode("utf-8")
  return response


def makeSequencePost(responses):
  calls = []

  def fakePost(url, **kwargs):
    calls.append(kwargs)
    return responses[len(calls) - 1]

  fakePost.calls = calls
  return fakePost


def makeSuccessPayload(content):
  return {
    "id": "gen-1", "model": "openai/gpt-6-luna",
    "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
    "usage": {"prompt_tokens": 2000, "completion_tokens": 20, "total_tokens": 2020},
  }


@pytest.fixture
def recordedSleeps(monkeypatch):
  sleeps = []
  monkeypatch.setattr(text2sql.time, "sleep", sleeps.append)
  return sleeps


def testCallOpenRouterRetriesRateLimitThenSucceeds(monkeypatch, modelEnv, recordedSleeps):
  modelEnv(OPENROUTER_API_KEY="test-key")
  fakePost = makeSequencePost([
    makeOpenRouterResponse(429, {"error": {"code": 429, "message": "Rate limit exceeded"}}),
    makeOpenRouterResponse(200, makeSuccessPayload("SELECT 1")),
  ])
  monkeypatch.setattr(text2sql.requests, "post", fakePost)

  reply = text2sql.callCloudModel([{"role": "user", "content": "問題"}], provider="openrouter", model="openai/gpt-6-luna")

  assert reply == "SELECT 1"
  assert len(fakePost.calls) == 2
  assert recordedSleeps == [2]


def testCallOpenRouterGivesUpAfterThreeAttempts(monkeypatch, modelEnv, recordedSleeps):
  modelEnv(OPENROUTER_API_KEY="test-key")
  unavailable = {"error": {"code": 503, "message": "Service unavailable"}}
  fakePost = makeSequencePost([makeOpenRouterResponse(503, unavailable) for _ in range(3)])
  monkeypatch.setattr(text2sql.requests, "post", fakePost)

  with pytest.raises(requests.HTTPError):
    text2sql.callCloudModel([{"role": "user", "content": "問題"}], provider="openrouter", model="openai/gpt-6-luna")

  assert len(fakePost.calls) == 3
  assert recordedSleeps == [2, 4]


def testCallOpenRouterDoesNotRetryAuthError(monkeypatch, modelEnv, recordedSleeps):
  modelEnv(OPENROUTER_API_KEY="wrong-key")
  fakePost = makeSequencePost([makeOpenRouterResponse(401, {"error": {"code": 401, "message": "No auth credentials found"}})])
  monkeypatch.setattr(text2sql.requests, "post", fakePost)

  with pytest.raises(requests.HTTPError):
    text2sql.callCloudModel([{"role": "user", "content": "問題"}], provider="openrouter", model="openai/gpt-6-luna")

  assert len(fakePost.calls) == 1
  assert recordedSleeps == []


def testCallOpenRouterRaisesRequestErrorWhenChoicesMissing(monkeypatch, modelEnv, recordedSleeps):
  modelEnv(OPENROUTER_API_KEY="test-key", OPENROUTER_MODELS="openai/gpt-6-luna")
  upstreamError = {"error": {"code": 502, "message": "Upstream provider error"}}
  monkeypatch.setattr(text2sql.requests, "post", makeSequencePost([makeOpenRouterResponse(200, upstreamError)]))

  with pytest.raises(requests.RequestException) as raised:
    text2sql.callCloudModel([{"role": "user", "content": "問題"}], provider="openrouter", model="openai/gpt-6-luna")

  # app 只接 RequestException，訊息要看得出是上游出錯
  assert "Upstream provider error" in text2sql.describeLlmError(raised.value, "openai/gpt-6-luna")


googleModels = "gemini-3.5-flash-lite,gemini-3.8-flash"
sqlReply = "```sql" + chr(10) + "SELECT 1" + chr(10) + "```"


def testListModelsAddsGoogleModelsWithOnlyGoogleKey(modelEnv):
  modelEnv(OLLAMA_MODEL="qwen2.5:3b", LOCAL_MODELS="qwen2.5:3b", OPENROUTER_MODELS=cloudModels,
           GOOGLE_AI_API_KEY="google-key", GOOGLE_AI_MODELS=googleModels)
  assert text2sql.listModels() == ["qwen2.5:3b", "gemini-3.5-flash-lite", "gemini-3.8-flash"]


def testModelInBothCloudListsGoesToOpenRouterOnce(modelEnv):
  modelEnv(OLLAMA_MODEL="qwen2.5:3b", LOCAL_MODELS="qwen2.5:3b",
           OPENROUTER_API_KEY="openrouter-key", OPENROUTER_MODELS="gemini-3.5-flash-lite",
           GOOGLE_AI_API_KEY="google-key", GOOGLE_AI_MODELS="gemini-3.5-flash-lite")
  assert text2sql.listModels() == ["qwen2.5:3b", "gemini-3.5-flash-lite"]
  assert text2sql.getProvider("gemini-3.5-flash-lite") == "openrouter"


def testGetLlmRoutesGoogleModels(modelEnv):
  modelEnv(GOOGLE_AI_MODELS=googleModels)
  googleLlm = text2sql.getLlm("gemini-3.5-flash-lite")
  assert googleLlm.func is text2sql.callCloudModel
  assert googleLlm.keywords == {"provider": "google", "model": "gemini-3.5-flash-lite"}


def testCallCloudModelSendsGoogleRequest(monkeypatch, modelEnv):
  modelEnv(GOOGLE_AI_API_KEY="google-key")
  fakePost = makeFakePost(sqlReply)
  monkeypatch.setattr(text2sql.requests, "post", fakePost)
  messages = [{"role": "user", "content": "問題"}]

  reply = text2sql.callCloudModel(messages, provider="google", model="gemini-3.5-flash-lite")

  call = fakePost.calls[0]
  assert reply == sqlReply
  assert call["url"] == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
  assert call["headers"] == {"Authorization": "Bearer google-key"}
  assert call["json"] == {"model": "gemini-3.5-flash-lite", "messages": messages, "temperature": 0}
  assert call["timeout"] == 60


def testDescribeModelMarksGoogleAsCloud(modelEnv):
  modelEnv(GOOGLE_AI_MODELS=googleModels)
  assert text2sql.describeModel("gemini-3.5-flash-lite") == "gemini-3.5-flash-lite（雲端）"


def testDescribeLlmErrorExplainsGoogleBillingAndQuota(modelEnv):
  modelEnv(GOOGLE_AI_MODELS=googleModels)
  assert text2sql.describeLlmError(makeHttpError(403, "{}"), "gemini-3.5-flash-lite") == (
    "無法呼叫 Google（HTTP 403）：請確認 AI Studio 已綁定帳單，而且 key 屬於有 credits 的專案"
  )
  assert text2sql.describeLlmError(makeHttpError(429, "{}"), "gemini-3.5-flash-lite") == (
    "無法呼叫 Google（HTTP 429）：額度用完或呼叫太頻繁，請到 AI Studio 查看用量"
  )


def testDescribeLlmErrorShowsGoogleBodyForInvalidKey(modelEnv):
  modelEnv(GOOGLE_AI_MODELS=googleModels)
  body = '{"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.", "status": "INVALID_ARGUMENT"}}'

  message = text2sql.describeLlmError(makeHttpError(400, body), "gemini-3.5-flash-lite")

  assert message.startswith("無法呼叫 Google（HTTP 400）：")
  assert "API key not valid" in message


def testDescribeLlmErrorWithoutResponseNamesGoogle(modelEnv):
  modelEnv(GOOGLE_AI_MODELS=googleModels)
  error = requests.ConnectionError("連不上")
  assert text2sql.describeLlmError(error, "gemini-3.5-flash-lite") == "無法呼叫 Google：連不上"


@pytest.mark.parametrize("payload", [
  {"choices": []},
  [{"error": {"code": 400, "message": "API key not valid. Please pass a valid API key."}}],
  None,
])
def testCallCloudModelRaisesRequestErrorForMalformedPayload(monkeypatch, modelEnv, payload):
  modelEnv(GOOGLE_AI_API_KEY="google-key")
  monkeypatch.setattr(text2sql.requests, "post", makeSequencePost([makeOpenRouterResponse(200, payload)]))

  with pytest.raises(requests.RequestException):
    text2sql.callCloudModel([{"role": "user", "content": "問題"}], provider="google", model="gemini-3.5-flash-lite")


@pytest.mark.parametrize("choice", [
  {"index": 0, "finish_reason": "content_filter", "message": {"role": "assistant"}},
  {"index": 0, "finish_reason": "content_filter"},
])
def testCallCloudModelTreatsBlockedAnswerAsEmpty(monkeypatch, modelEnv, choice):
  modelEnv(GOOGLE_AI_API_KEY="google-key")
  monkeypatch.setattr(text2sql.requests, "post", makeSequencePost([makeOpenRouterResponse(200, {"choices": [choice]})]))

  # 被安全機制擋下是模型沒有給出答案，要算答錯，不能當成連線錯誤而不計分
  reply = text2sql.callCloudModel([{"role": "user", "content": "問題"}], provider="google", model="gemini-3.5-flash-lite")

  assert reply == ""


def testCallOllamaFixesContextLength(monkeypatch, modelEnv):
  sent = {}

  def fakePost(url, json, timeout):
    sent.update(json)
    return makeOpenRouterResponse(200, {"message": {"role": "assistant", "content": "SELECT 1"}})

  monkeypatch.setattr(text2sql.requests, "post", fakePost)

  assert text2sql.callOllama([{"role": "user", "content": "問題"}]) == "SELECT 1"
  assert sent["options"] == {"temperature": 0, "num_ctx": 8192}


def testPromptListsOrganizationVocabulary(demoDatabaseUrl):
  messages = text2sql.buildMessages("問題", db.getLlmSchemaText(), db.getVocabulary(demoDatabaseUrl), fixedNow)
  systemPrompt = messages[0]["content"]

  assert "- departments.name：" in systemPrompt
  assert "營運部" in systemPrompt
  assert "- leave_requests.status：" in systemPrompt
  assert "approved" in systemPrompt
