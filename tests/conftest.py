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


@pytest.fixture
def databaseUrl(testDatabaseUrl):
  # 每個測試用自己的 schema，彼此的資料不會互相影響，自動編號也都從 1 開始
  with db.temporarySchema(testDatabaseUrl, "test") as url:
    db.initDb(url)
    yield url
