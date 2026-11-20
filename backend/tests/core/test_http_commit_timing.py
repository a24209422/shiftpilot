import socket
import threading
import time
from contextlib import contextmanager

import httpx
import psycopg
import uvicorn
from psycopg.rows import dict_row

from app.infra import http
from app.main import createApp


@contextmanager
def slowCommitDb(databaseUrl):
  # 跟 openDb 一樣，只是在 commit 之前多等一下，把「回應送出」和「資料 commit」之間的空隙拉大
  with psycopg.connect(databaseUrl, row_factory=dict_row) as conn:
    yield conn
    time.sleep(0.5)


@contextmanager
def runServer(app):
  with socket.socket() as probe:
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
  server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
  thread = threading.Thread(target=server.run, daemon=True)
  thread.start()
  while not server.started:
    time.sleep(0.05)
  try:
    yield f"http://127.0.0.1:{port}"
  finally:
    server.should_exit = True
    thread.join(timeout=10)


def testLoginIsCommittedBeforeTheResponseIsSent(migratedUrl, makeUser, monkeypatch):
  # TestClient 會等整個應用程式（包含回應送出之後的清理）跑完才回傳，看不到這個空隙；
  # 真的走 socket 時，新版 FastAPI 預設在回應送出「之後」才執行 yield 依賴的收尾（commit），
  # 瀏覽器拿到登入成功就立刻送下一個請求，會碰到還沒 commit 的 session 而被當成未登入
  _, password = makeUser("employee", "emp@example.com")
  monkeypatch.setattr(http, "openDb", slowCommitDb)
  with runServer(createApp(migratedUrl)) as base:
    with httpx.Client(base_url=base, headers={"X-App-Client": "web"}) as client:
      assert client.post("/api/auth/login", json={"email": "emp@example.com", "password": password}).status_code == 200
      assert client.get("/api/auth/me").status_code == 200


def testErrorAfterWriteRollsBackTheWholeRequest(migratedUrl):
  # 守門測試：改成「端點結束就收尾」之後，端點丟出的例外仍然要傳進連線的收尾，把這個請求寫的東西全部 rollback
  from fastapi.testclient import TestClient

  from app.infra.db import openDb
  from app.infra.errors import AppError

  app = createApp(migratedUrl)

  @app.post("/api/test/boom")
  def boom(conn=http.connDependency):
    conn.execute("INSERT INTO departments (name) VALUES ('不該留下')")
    raise AppError("BOOM", "寫完之後才失敗", 400)

  @app.post("/api/test/fine")
  def fine(conn=http.connDependency):
    conn.execute("INSERT INTO departments (name) VALUES ('要留下')")
    return {"ok": True}

  client = TestClient(app, headers={"X-App-Client": "web"})
  assert client.post("/api/test/boom").status_code == 400
  assert client.post("/api/test/fine").status_code == 200
  with openDb(migratedUrl) as conn:
    names = [row["name"] for row in conn.execute("SELECT name FROM departments").fetchall()]
  assert names == ["要留下"]
