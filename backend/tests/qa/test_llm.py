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


def testSameIdInLocalAndCloudResolvesToOllama(monkeypatch):
  monkeypatch.setenv("LOCAL_MODELS", "shared-model")
  monkeypatch.setenv("OPENROUTER_API_KEY", "key")
  monkeypatch.setenv("OPENROUTER_MODELS", "shared-model")
  assert llm.getProvider("shared-model") == "ollama"
  assert llm.getProvider("anthropic/claude-haiku-5.5") == "ollama"
