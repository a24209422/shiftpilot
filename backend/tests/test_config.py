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


def testCreateAppFromEnvReadsTheDotEnvFile(tmp_path, monkeypatch):
  # README 的啟動指令沒有先 export 環境變數：.env 裡的設定一定要被讀進來
  from app import config
  from app.main import createAppFromEnv

  envFile = tmp_path / ".env"
  envFile.write_text("DATABASE_URL=postgresql://from-dotenv\n", encoding="utf-8")
  monkeypatch.setenv("DATABASE_URL", "placeholder")
  monkeypatch.delenv("DATABASE_URL")
  monkeypatch.setattr(config, "envFilePath", envFile)
  assert createAppFromEnv().state.databaseUrl == "postgresql://from-dotenv"
