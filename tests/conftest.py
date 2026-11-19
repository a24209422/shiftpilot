import os

import pytest
from dotenv import load_dotenv

import db

load_dotenv()


@pytest.fixture(scope="session")
def testDatabaseUrl():
  url = os.getenv("TEST_DATABASE_URL")
  if not url:
    pytest.fail("請在 .env 設定 TEST_DATABASE_URL（參考 .env.example），並先執行 docker compose up -d")
  return url


modelEnvNames = ["OLLAMA_MODEL", "OLLAMA_MODELS", "LOCAL_MODELS", "OPENROUTER_API_KEY", "OPENROUTER_MODELS"]


@pytest.fixture
def modelEnv(monkeypatch):
  # 上面的 load_dotenv 會載入真正的 .env，使用者填了 key 之後測試結果不能跟著變
  for name in modelEnvNames:
    monkeypatch.delenv(name, raising=False)

  def setEnv(**values):
    for name, value in values.items():
      monkeypatch.setenv(name, value)

  return setEnv


@pytest.fixture
def databaseUrl(testDatabaseUrl):
  # 每個測試用自己的 schema，彼此的資料不會互相影響，自動編號也都從 1 開始
  with db.temporarySchema(testDatabaseUrl, "test") as url:
    db.initDb(url)
    yield url
