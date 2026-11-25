import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.main import createApp
from app.infra import http
from app.infra.errors import AppError
from app.modules.qa import llm, service
from app.modules.qa.llm import LlmUnavailableError, ToolReply


path = "/api/qa/ask/stream"
# 這些測試驗證串流機制本身，固定用 pipeline 才能只換掉 callModel；預設的 assistant-jev 會去呼叫 Jev
body = {"question": "有哪些員工？", "model": "fake", "mode": "pipeline"}
headers = {"X-App-Client": "web"}


@pytest.fixture
def client(migratedUrl, qaSandboxUrl, monkeypatch):
  monkeypatch.setenv("OLLAMA_MODEL", "fake")
  monkeypatch.delenv("QA_MODE", raising=False)
  return TestClient(createApp(migratedUrl, qaDatabaseUrl=qaSandboxUrl), headers=headers)


def readEvents(response):
  assert response.headers["content-type"].startswith("application/x-ndjson")
  return [json.loads(line) for line in response.text.splitlines()]


def testStreamChecksExistingAccessRules(client, loginAs, monkeypatch):
  assert client.post(path, json=body).status_code == 401
  assert TestClient(client.app).post(path, json=body).json()["error"]["code"] == "CSRF"
  loginAs("employee", employee=True, client=client)
  assert client.post(path, json={**body, "question": " "}).status_code == 422
  assert client.post(path, json={**body, "mode": "invalid"}).status_code == 422
  monkeypatch.setattr(http, "hasPermission", lambda *_: False)
  assert client.post(path, json=body).status_code == 403


def testStreamResultMatchesJsonEndpoint(client, loginAs, monkeypatch):
  loginAs("employee", employee=True, client=client)
  replies = iter(["SELECT name FROM employees", "答覆"] * 2)
  monkeypatch.setattr(llm, "callModel", lambda *_: next(replies))
  normal = client.post("/api/qa/ask", json=body)
  assert normal.status_code == 200, normal.text
  response = client.post(path, json=body)
  events = readEvents(response)
  assert response.headers["cache-control"] == "no-store"
  assert events[0] == {"type": "accepted"}
  assert [event for event in events if event["type"] in ("result", "error")] == [
    {"type": "result", "answer": normal.json()},
  ]


def testAcceptedFailureHasExactlyOneTerminalEvent(client, loginAs, monkeypatch):
  loginAs("employee", employee=True, client=client)

  def unavailable(*_):
    raise LlmUnavailableError("模型離線")

  monkeypatch.setattr(llm, "callModel", unavailable)
  events = readEvents(client.post(path, json=body))
  assert events[-2] == {"type": "step", "id": 2, "stage": "generate_query", "state": "failed"}
  assert [event for event in events if event["type"] in ("result", "error")] == [{
    "type": "error", "status": 503,
    "error": {"code": "QA_MODEL_UNAVAILABLE", "message": "模型離線", "details": None},
  }]


def testUnserializableErrorTerminatesTheStream(monkeypatch):
  from app.modules.qa.stream import QuestionStream

  def ask(emit):
    emit({"type": "accepted"})
    raise AppError("QA_QUERY_FAILED", "查詢失敗", 422, {"invalid": float("inf")})

  async def drive():
    stream = QuestionStream()
    await asyncio.wait_for(asyncio.to_thread(stream.run, ask), timeout=2)
    assert json.loads(stream.outgoing.get_nowait()) == {"type": "accepted"}
    assert json.loads(stream.outgoing.get_nowait()) == {
      "type": "error", "status": 500,
      "error": {"code": "INTERNAL_ERROR", "message": "系統發生未預期的錯誤", "details": None},
    }
    assert stream.outgoing.get_nowait() is None

  asyncio.run(drive())


def testConcurrentUsersReceiveTheirOwnEventsAndRespectTotalCapacity(client, loginAs, monkeypatch):
  models = [f"fake-{i}" for i in range(4)]
  clients = [TestClient(client.app, headers=headers) for _ in models]
  for index, userClient in enumerate(clients):
    loginAs("employee", email=f"stream{index}@example.test", employee=True, client=userClient)
  monkeypatch.setattr(llm, "listModels", lambda: [{"id": name, "remote": False} for name in models])
  entered = threading.Barrier(4, timeout=8)
  release = threading.Event()

  def fakeModel(model, *_):
    entered.wait()
    assert release.wait(8)
    return ToolReply(model, [], None, None)

  monkeypatch.setattr(llm, "callModelWithTools", fakeModel)

  def ask(index):
    return clients[index].post(path, json={**body, "model": models[index], "mode": "assistant"})

  with ThreadPoolExecutor(max_workers=3) as executor:
    futures = [executor.submit(ask, index) for index in range(3)]
    try:
      entered.wait()
      response = ask(3)
      assert response.status_code == 429
      assert response.json()["error"]["code"] == "QA_BUSY"
    finally:
      release.set()
    for model, future in zip(models, futures):
      events = readEvents(future.result(timeout=8))
      assert events[0] == {"type": "accepted"}
      assert [event["id"] for event in events if event["type"] == "step"] == [1, 1, 2, 2]
      assert events[-1]["answer"]["answer"] == model


@pytest.mark.parametrize("disconnect", [False, True])
def testProgressReachesClientWhileModelIsPaused(client, loginAs, monkeypatch, disconnect):
  loginAs("employee", employee=True, client=client)
  release = threading.Event()
  entered = threading.Event()
  calls = []
  events = []
  replies = iter(["SELECT name FROM employees", "答覆"])

  def fakeModel(*_):
    calls.append(1)
    entered.set()
    assert release.wait(8)
    return next(replies)

  monkeypatch.setattr(llm, "callModel", fakeModel)

  async def drive():
    incoming = asyncio.Queue()
    incoming.put_nowait({"type": "http.request", "body": json.dumps(body).encode()})

    async def send(message):
      if message["type"] != "http.response.body" or not message.get("body"):
        return
      for line in message["body"].splitlines():
        event = json.loads(line)
        events.append(event)
        if event.get("stage") == "generate_query" and event["state"] == "running":
          assert await asyncio.to_thread(entered.wait, 2)
          assert not release.is_set()
          assert not any(item["type"] == "result" for item in events)
          if disconnect:
            incoming.put_nowait({"type": "http.disconnect"})
          else:
            release.set()

    scope = {
      "type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"}, "method": "POST",
      "path": path, "query_string": b"", "headers": [
        (b"cookie", f"sid={client.cookies['sid']}".encode()),
        (b"x-app-client", b"web"), (b"content-type", b"application/json"),
      ],
    }
    try:
      await asyncio.wait_for(client.app(scope, incoming.get, send), 5)
      if disconnect:
        busy = await asyncio.to_thread(client.post, path, json=body)
        assert busy.status_code == 429
        assert busy.json()["error"]["code"] == "QA_USER_BUSY"
    finally:
      release.set()

  asyncio.run(drive())
  assert not service.askingUserIds
  if disconnect:
    assert len(calls) == 1
    assert events[-1]["state"] == "running"
  else:
    assert events[-1]["answer"]["answer"] == "答覆"
