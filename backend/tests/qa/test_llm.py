import json

import httpx
import pytest

from app.modules.qa import llm


@pytest.fixture(autouse=True)
def cleanEnv(monkeypatch):
  for name in ("OLLAMA_URL", "OLLAMA_MODEL", "LOCAL_MODELS", "OPENROUTER_API_KEY", "OPENROUTER_MODELS", "GOOGLE_AI_API_KEY", "GOOGLE_AI_MODELS"):
    monkeypatch.delenv(name, raising=False)
  monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:3b")


def clientWith(handler):
  return httpx.Client(transport=httpx.MockTransport(handler))


def testListModelsLocalFirstAndCloudOnlyWithKey(monkeypatch):
  monkeypatch.setenv("LOCAL_MODELS", "qwen3-vl:4b-instruct, qwen2.5:3b")
  monkeypatch.setenv("OPENROUTER_MODELS", "anthropic/claude-haiku-5.5")
  assert llm.listModels() == [
    {"id": "qwen2.5:3b", "label": "qwen2.5:3b（本機）", "remote": False},
    {"id": "qwen3-vl:4b-instruct", "label": "qwen3-vl:4b-instruct（本機）", "remote": False},
  ]
  monkeypatch.setenv("OPENROUTER_API_KEY", "key")
  assert llm.listModels()[-1] == {"id": "anthropic/claude-haiku-5.5", "label": "anthropic/claude-haiku-5.5（OpenRouter）", "remote": True}


def testCallOllamaSendsTemperatureZero(monkeypatch):
  seen = {}

  def handler(request):
    seen["url"] = str(request.url)
    seen["body"] = json.loads(request.content)
    return httpx.Response(200, json={"message": {"content": "SELECT 1"}})

  monkeypatch.setenv("OLLAMA_URL", "http://ollama:11434/")
  assert llm.callModel("qwen2.5:3b", [{"role": "user", "content": "hi"}], client=clientWith(handler)) == "SELECT 1"
  assert seen["url"] == "http://ollama:11434/api/chat"
  assert seen["body"]["options"] == {"temperature": 0, "num_ctx": 8192}
  assert seen["body"]["stream"] is False


def testOllamaConnectionErrorIsExplained():
  def handler(request):
    raise httpx.ConnectError("refused")

  with pytest.raises(llm.LlmUnavailableError) as info:
    llm.callModel("qwen2.5:3b", [], client=clientWith(handler))
  assert "Ollama" in info.value.message and "qwen2.5:3b" in info.value.message


def testCloudRetriesOn429ThenSucceeds(monkeypatch):
  monkeypatch.setenv("OPENROUTER_API_KEY", "key")
  monkeypatch.setenv("OPENROUTER_MODELS", "m1")
  replies = [httpx.Response(429, text="slow down"), httpx.Response(200, json={"choices": [{"message": {"content": "SELECT 2"}}]})]
  waits = []

  def handler(request):
    assert request.headers["Authorization"] == "Bearer key"
    return replies.pop(0)

  assert llm.callModel("m1", [], client=clientWith(handler), sleep=waits.append) == "SELECT 2"
  assert waits == [2]


def testCloudAuthErrorUsesHint(monkeypatch):
  monkeypatch.setenv("OPENROUTER_API_KEY", "bad")
  monkeypatch.setenv("OPENROUTER_MODELS", "m1")
  with pytest.raises(llm.LlmUnavailableError) as info:
    llm.callModel("m1", [], client=clientWith(lambda request: httpx.Response(401, text="no")), sleep=lambda seconds: None)
  assert "OPENROUTER_API_KEY" in info.value.message


def testCloudWithoutChoicesIsUnavailable(monkeypatch):
  monkeypatch.setenv("OPENROUTER_API_KEY", "key")
  monkeypatch.setenv("OPENROUTER_MODELS", "m1")
  with pytest.raises(llm.LlmUnavailableError):
    llm.callModel("m1", [], client=clientWith(lambda request: httpx.Response(200, json={"error": "x"})))


def testOllamaNon200JsonBodyIsFormatError():
  # 代理或閘道在 200 時回 HTML，json() 會丟出 ValueError，要轉成可讀的錯誤
  with pytest.raises(llm.LlmUnavailableError) as info:
    llm.callModel("qwen2.5:3b", [], client=clientWith(lambda request: httpx.Response(200, text="<html>gateway</html>")))
  assert info.value.message == "Ollama 的回應格式不正確"


def testOllamaMissingMessageIsFormatError():
  with pytest.raises(llm.LlmUnavailableError) as info:
    llm.callModel("qwen2.5:3b", [], client=clientWith(lambda request: httpx.Response(200, json={})))
  assert info.value.message == "Ollama 的回應格式不正確"


def testCloudRetryExhaustionRaisesAfterThreeRetries(monkeypatch):
  monkeypatch.setenv("OPENROUTER_API_KEY", "key")
  monkeypatch.setenv("OPENROUTER_MODELS", "m1")
  replies = [httpx.Response(503, text="busy") for _ in range(3)]
  waits = []

  with pytest.raises(llm.LlmUnavailableError):
    llm.callModel("m1", [], client=clientWith(lambda request: replies.pop(0)), sleep=waits.append)
  assert waits == [2, 4]


def testCloudErrorBodyEchoingKeyIsRedacted(monkeypatch):
  monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-123456")
  monkeypatch.setenv("OPENROUTER_MODELS", "m1")
  body = "invalid key sk-test-123456"
  with pytest.raises(llm.LlmUnavailableError) as info:
    llm.callModel("m1", [], client=clientWith(lambda request: httpx.Response(400, text=body)))
  assert "sk-test-123456" not in info.value.message
  assert "***" in info.value.message


def testKeyStraddlingTruncationBoundaryIsFullyRedacted(monkeypatch):
  key = "sk-test-123456"
  monkeypatch.setenv("OPENROUTER_API_KEY", key)
  monkeypatch.setenv("OPENROUTER_MODELS", "m1")
  # key 從第 295 個字元開始，會跨過 300 的截斷邊界
  body = "x" * 295 + key + "tail"
  with pytest.raises(llm.LlmUnavailableError) as info:
    llm.callModel("m1", [], client=clientWith(lambda request: httpx.Response(400, text=body)))
  assert "sk-te" not in info.value.message
  assert "***" in info.value.message


def testSameIdInLocalAndCloudResolvesToOllama(monkeypatch):
  monkeypatch.setenv("LOCAL_MODELS", "shared-model")
  monkeypatch.setenv("OPENROUTER_API_KEY", "key")
  monkeypatch.setenv("OPENROUTER_MODELS", "shared-model")
  assert llm.getProvider("shared-model") == "ollama"
  assert llm.getProvider("anthropic/claude-haiku-5.5") == "ollama"


tools = [{"type": "function", "function": {"name": "run_sql", "description": "x", "parameters": {"type": "object", "properties": {}}}}]
conversation = [
  {"role": "user", "content": "hi"},
  {"role": "assistant", "content": "", "toolCalls": [llm.ToolCall("abc", "run_sql", {"sql": "SELECT 1"}, '{"sql": "SELECT 1"}')]},
  {"role": "tool", "toolCallId": "abc", "name": "run_sql", "content": "結果"},
]


def cloudEnv(monkeypatch):
  monkeypatch.setenv("OPENROUTER_API_KEY", "key")
  monkeypatch.setenv("OPENROUTER_MODELS", "m1")


def cloudReply(message, usage=None):
  payload = {"choices": [{"message": message}]}
  if usage:
    payload["usage"] = usage
  return httpx.Response(200, json=payload)


def testOllamaToolCallsAreParsed():
  seen = {}

  def handler(request):
    seen["body"] = json.loads(request.content)
    return httpx.Response(200, json={
      "message": {"content": "", "tool_calls": [{"function": {"name": "run_sql", "arguments": {"sql": "SELECT 1"}}}]},
      "prompt_eval_count": 120, "eval_count": 8,
    })

  reply = llm.callModelWithTools("qwen2.5:3b", [{"role": "user", "content": "hi"}], tools, client=clientWith(handler))
  assert seen["body"]["tools"] == tools
  assert seen["body"]["options"] == {"temperature": 0, "num_ctx": 8192}
  assert reply.toolCalls[0].name == "run_sql" and reply.toolCalls[0].arguments == {"sql": "SELECT 1"}
  assert reply.toolCalls[0].id
  assert (reply.promptTokens, reply.completionTokens) == (120, 8)
  assert reply.content == ""


def testOllamaMessagesAreConverted():
  seen = {}

  def handler(request):
    seen["body"] = json.loads(request.content)
    return httpx.Response(200, json={"message": {"content": "好"}})

  reply = llm.callModelWithTools("qwen2.5:3b", conversation, tools, client=clientWith(handler))
  assert reply.content == "好" and reply.toolCalls == []
  assert (reply.promptTokens, reply.completionTokens) == (None, None)
  sent = seen["body"]["messages"]
  assert sent[1] == {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "run_sql", "arguments": {"sql": "SELECT 1"}}}]}
  assert sent[2] == {"role": "tool", "content": "結果"}


def testCloudToolCallsAndUsage(monkeypatch):
  cloudEnv(monkeypatch)
  message = {"content": None, "tool_calls": [{"id": "abc", "type": "function", "function": {
    "name": "get_busy_periods", "arguments": '{"start": "2026-11-24 12:00"}'}}]}
  handler = lambda request: cloudReply(message, {"prompt_tokens": 300, "completion_tokens": 20})
  reply = llm.callModelWithTools("m1", [], tools, client=clientWith(handler))
  assert reply.toolCalls[0].id == "abc" and reply.toolCalls[0].arguments == {"start": "2026-11-24 12:00"}
  assert (reply.promptTokens, reply.completionTokens) == (300, 20)
  assert reply.content == ""


def testCloudMessagesAreConverted(monkeypatch):
  cloudEnv(monkeypatch)
  seen = {}

  def handler(request):
    seen["body"] = json.loads(request.content)
    return cloudReply({"content": "好"})

  llm.callModelWithTools("m1", conversation, tools, client=clientWith(handler))
  sent = seen["body"]["messages"]
  assert sent[1] == {"role": "assistant", "content": "", "tool_calls": [
    {"id": "abc", "type": "function", "function": {"name": "run_sql", "arguments": '{"sql": "SELECT 1"}'}}]}
  assert sent[2] == {"role": "tool", "tool_call_id": "abc", "content": "結果"}
  assert seen["body"]["tools"] == tools and seen["body"]["temperature"] == 0


def testCloudInvalidArgumentsJsonKeepsRaw(monkeypatch):
  cloudEnv(monkeypatch)
  message = {"content": "", "tool_calls": [{"id": "x", "type": "function", "function": {"name": "run_sql", "arguments": "{start: oops"}}]}
  reply = llm.callModelWithTools("m1", [], tools, client=clientWith(lambda request: cloudReply(message)))
  assert reply.toolCalls[0].arguments is None and reply.toolCalls[0].rawArguments == "{start: oops"


def testToolCallRetriesAndRedactionMatchCallModel(monkeypatch):
  cloudEnv(monkeypatch)
  replies = [httpx.Response(429, text="slow"), cloudReply({"content": "好"})]
  waits = []
  reply = llm.callModelWithTools("m1", [], tools, client=clientWith(lambda request: replies.pop(0)), sleep=waits.append)
  assert reply.content == "好" and waits == [2]
  with pytest.raises(llm.LlmUnavailableError) as info:
    llm.callModelWithTools("m1", [], tools, client=clientWith(lambda request: httpx.Response(401, text="no")), sleep=lambda seconds: None)
  assert "OPENROUTER_API_KEY" in info.value.message


def testCloudExtraToolCallFieldsAreEchoed(monkeypatch):
  # Gemini 這類供應商會在 tool_calls 附額外欄位，下一輪要原樣帶回
  cloudEnv(monkeypatch)
  rawCall = {"id": "abc", "type": "function", "function": {"name": "run_sql", "arguments": '{"sql": "SELECT 1"}'},
             "extra_content": {"google": {"thought_signature": "sig"}}}
  first = llm.callModelWithTools("m1", [], tools, client=clientWith(lambda request: cloudReply({"content": "", "tool_calls": [rawCall]})))
  seen = {}

  def handler(request):
    seen["body"] = json.loads(request.content)
    return cloudReply({"content": "好"})

  history = [{"role": "assistant", "content": "", "toolCalls": first.toolCalls},
             {"role": "tool", "toolCallId": "abc", "name": "run_sql", "content": "結果"}]
  llm.callModelWithTools("m1", history, tools, client=clientWith(handler))
  assert seen["body"]["messages"][0]["tool_calls"] == [rawCall]
