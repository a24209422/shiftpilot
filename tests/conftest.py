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


emptiedModelEnvNames = [
  "OLLAMA_MODELS", "LOCAL_MODELS", "OPENROUTER_API_KEY", "OPENROUTER_MODELS", "GOOGLE_AI_API_KEY", "GOOGLE_AI_MODELS",
]


@pytest.fixture
def modelEnv(monkeypatch):
  # 上面的 load_dotenv 會載入真正的 .env，使用者填了 key 之後測試結果不能跟著變。
  # 設成空字串而不是刪掉：evals.run.main 會再呼叫 load_dotenv，被刪掉的變數會從 .env 載回來
  for name in emptiedModelEnvNames:
    monkeypatch.setenv(name, "")
  # OLLAMA_MODEL 要真的刪掉，才測得到預設值；它被載回來也只影響預設模型，不會呼叫雲端
  monkeypatch.delenv("OLLAMA_MODEL", raising=False)

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
