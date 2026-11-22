import pytest
from fastapi.testclient import TestClient

from app.main import createApp
from app.modules.qa import jev as qaJev
from app.modules.qa import llm as qaLlm
from app.modules.qa.jev import JevDecision
from app.modules.qa.llm import LlmUnavailableError, ToolCall, ToolReply


@pytest.fixture
def qaClient(migratedUrl, qaSandboxUrl, monkeypatch):
  monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:3b")
  for name in ("LOCAL_MODELS", "OPENROUTER_API_KEY", "GOOGLE_AI_API_KEY"):
    monkeypatch.setenv(name, "")
  monkeypatch.delenv("QA_MODE", raising=False)
  return TestClient(createApp(migratedUrl, qaDatabaseUrl=qaSandboxUrl), headers={"X-App-Client": "web"})


def testModelsRequireLogin(qaClient):
  assert qaClient.get("/api/qa/models").status_code == 401


def testAskRequiresLogin(qaClient):
  assert qaClient.post("/api/qa/ask", json={"question": "有哪些員工？", "model": "qwen2.5:3b"}).status_code == 401


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
  assert body["sql"] == "SELECT name FROM employees" and body["remote"] is False
  assert set(body["window"]) == {"from", "to"}


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


def testAskAgentModeEndToEnd(qaClient, loginAs, monkeypatch):
  replies = iter([ToolReply("", [ToolCall("c1", "run_sql", {"sql": "SELECT name FROM employees"}, "")], None, None), ToolReply("一位。", [], None, None)])
  monkeypatch.setattr(qaLlm, "callModelWithTools", lambda model, messages, tools: next(replies))
  loginAs("employee", employee=True, client=qaClient)
  response = qaClient.post("/api/qa/ask", json={"question": "有哪些員工？", "model": "qwen2.5:3b", "mode": "agent"})
  assert response.status_code == 200, response.text
  body = response.json()
  assert body["mode"] == "agent" and len(body["steps"]) == 1 and body["answer"] == "一位。"


def testAskRejectsUnknownMode(qaClient, loginAs):
  loginAs("employee", employee=True, client=qaClient)
  response = qaClient.post("/api/qa/ask", json={"question": "有哪些員工？", "model": "qwen2.5:3b", "mode": "x"})
  assert response.status_code == 422


def testAskAcceptsJevMode(qaClient, loginAs, monkeypatch):
  replies = iter([
    ToolReply("", [ToolCall("c1", "run_sql", {"sql": "SELECT name FROM employees"}, "")], 10, 2),
    ToolReply("有一位員工。", [], 5, 1),
  ])
  monkeypatch.setattr(qaLlm, "callModelWithTools", lambda model, messages, tools: next(replies))
  monkeypatch.setattr(qaJev, "isConfigured", lambda: True)
  monkeypatch.setattr(qaJev, "chooseTool", lambda question, now: JevDecision("run_sql", 0.95, None, 440, 0.1))
  loginAs("employee", employee=True, client=qaClient)
  response = qaClient.post("/api/qa/ask", json={"question": "有哪些員工？", "model": "qwen2.5:3b", "mode": "jev"})
  assert response.status_code == 200, response.text
  body = response.json()
  assert body["mode"] == "jev" and body["route"]["tool"] == "run_sql" and body["route"]["promptTokens"] == 440
