import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

# .env 放在 repo 根目錄，不在 backend/ 底下
load_dotenv(Path(__file__).resolve().parents[2] / ".env")


@pytest.fixture(scope="session")
def testDatabaseUrl():
  url = os.getenv("TEST_DATABASE_URL")
  if not url:
    pytest.fail("請在 .env 設定 TEST_DATABASE_URL（參考 .env.example），並先執行 docker compose up -d")
  return url
