import pytest

from app.config import loadConfig


def testLoadConfigReadsDatabaseUrl(monkeypatch):
  monkeypatch.setenv("DATABASE_URL", "postgresql://x")
  config = loadConfig()
  assert config.databaseUrl == "postgresql://x"
  assert config.sessionHours == 12


def testLoadConfigRequiresDatabaseUrl(monkeypatch):
  monkeypatch.delenv("DATABASE_URL", raising=False)
  with pytest.raises(RuntimeError, match="DATABASE_URL"):
    loadConfig()
