import pytest
from fastapi.testclient import TestClient

from app.main import createApp
from app.modules.qa import llm as qaLlm
from app.modules.qa.llm import LlmUnavailableError


@pytest.fixture
def qaClient(migratedUrl, qaSandboxUrl, monkeypatch):
  monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:3b")
  for name in ("LOCAL_MODELS", "OPENROUTER_API_KEY", "GOOGLE_AI_API_KEY"):
    monkeypatch.setenv(name, "")
  return TestClient(createApp(migratedUrl, qaDatabaseUrl=qaSandboxUrl), headers={"X-App-Client": "web"})


def testModelsRequireLogin(qaClient):
  assert qaClient.get("/api/qa/models").status_code == 401


def testModelsList(qaClient, loginAs):
  loginAs("employee", employee=True, client=qaClient)
  assert qaClient.get("/api/qa/models").json() == [{"id": "qwen2.5:3b", "label": "qwen2.5:3b（本機）", "remote": False}]


def testAskEndToEndWithFakeModel(qaClient, loginAs, monkeypatch):
  replies = iter(["SELECT name FROM employees", "有一位員工。"])
  monkeypatch.setattr(qaLlm, "callModel", lambda model, messages: next(replies))
  loginAs("employee", employee=True, client=qaClient)
  response = qaClient.post("/api/qa/ask", json={"question": "有哪些員工？", "model": "qwen2.5:3b"})
  assert response.status_code == 200, response.text
  body = response.json()
  assert body["answer"] == "有一位員工。" and body["columns"] == ["name"] and len(body["rows"]) == 1


def testAskModelUnavailableIs503(qaClient, loginAs, monkeypatch):
  def fail(model, messages):
    raise LlmUnavailableError("無法呼叫 Ollama：refused")

  monkeypatch.setattr(qaLlm, "callModel", fail)
  loginAs("employee", employee=True, client=qaClient)
  response = qaClient.post("/api/qa/ask", json={"question": "有哪些員工？", "model": "qwen2.5:3b"})
  assert response.status_code == 503 and response.json()["error"]["code"] == "QA_MODEL_UNAVAILABLE"


def testAskWithoutSandboxConfigured(migratedUrl, loginAs, monkeypatch):
  monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:3b")
  client = TestClient(createApp(migratedUrl), headers={"X-App-Client": "web"})
  loginAs("employee", employee=True, client=client)
  response = client.post("/api/qa/ask", json={"question": "有哪些員工？", "model": "qwen2.5:3b"})
  assert response.status_code == 503 and response.json()["error"]["code"] == "QA_NOT_CONFIGURED"
