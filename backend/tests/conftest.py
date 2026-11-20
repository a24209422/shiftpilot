import itertools
import os
from datetime import date
from pathlib import Path

import pytest
from dotenv import load_dotenv

from app.infra.db import ensureExtensions, openDb, temporarySchema
from app.infra.migrate import runMigrations
from app.modules import allModules
from app.modules.core import service as coreService
from app.modules.org import service as orgService

# .env 放在 repo 根目錄，不在 backend/ 底下
load_dotenv(Path(__file__).resolve().parents[2] / ".env")


@pytest.fixture(scope="session")
def testDatabaseUrl():
  url = os.getenv("TEST_DATABASE_URL")
  if not url:
    pytest.fail("請在 .env 設定 TEST_DATABASE_URL（參考 .env.example），並先執行 docker compose up -d")
  return url


@pytest.fixture
def databaseUrl(testDatabaseUrl):
  # 每個測試用自己的 schema，彼此的資料不會互相影響，自動編號也都從 1 開始
  ensureExtensions(testDatabaseUrl)
  with temporarySchema(testDatabaseUrl, "test") as url:
    yield url


@pytest.fixture
def migratedUrl(databaseUrl):
  runMigrations(databaseUrl, allModules)
  return databaseUrl


@pytest.fixture
def newClient(migratedUrl):
  # 延遲匯入：app.main 在任務 11 才存在，其他測試不該因為它還沒寫好而整批無法收集
  from fastapi.testclient import TestClient

  from app.main import createApp

  app = createApp(migratedUrl)

  def make():
    return TestClient(app, headers={"X-App-Client": "web"})

  return make


@pytest.fixture
def client(newClient):
  return newClient()


@pytest.fixture
def makeUser(migratedUrl):
  counter = itertools.count(1)

  def make(role="employee", email=None, employee=False, password="correct-horse-battery"):
    number = next(counter)
    with openDb(migratedUrl) as conn:
      employeeId = None
      if employee:
        departments = orgService.listDepartments(conn)
        departmentId = departments[0]["id"] if departments else orgService.createDepartment(conn, None, "測試部")["id"]
        employeeId = orgService.createEmployee(
          conn, None,
          {"employeeNo": f"T{number:03d}", "name": f"測試員工{number}", "departmentId": departmentId, "jobTitle": "工程師", "hiredOn": date(2025, 1, 1)},
        )["id"]
      user = coreService.createUser(conn, None, email or f"{role}{number}@example.com", password, role, employeeId)
    return user["id"], password

  return make


@pytest.fixture
def loginAs(client, makeUser):
  counter = itertools.count(1)

  def login(role="employee", email=None, employee=False, client=client):
    email = email or f"{role}-login{next(counter)}@example.com"
    userId, password = makeUser(role, email, employee)
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"userId": userId, "email": email, "password": password, "employeeId": response.json()["user"]["employeeId"]}

  return login
