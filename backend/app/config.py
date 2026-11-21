import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

from dotenv import load_dotenv

# .env 放在 repo 根目錄，不在 backend/ 底下
envFilePath = Path(__file__).resolve().parents[2] / ".env"
qaDbUser = "qa_sandbox"


@dataclass
class Config:
  databaseUrl: str
  sessionHours: int = 12
  qaDatabaseUrl: str | None = None


def loadEnvFile() -> None:
  # 已經設好的環境變數不會被 .env 蓋掉；檔案不存在（例如在容器裡）也不會出錯
  load_dotenv(envFilePath)


def buildQaDatabaseUrl(databaseUrl: str, password: str) -> str:
  # 主機、port、資料庫都跟 app 一樣，只換成沒有任何資料表權限的沙盒帳號
  parts = urlsplit(databaseUrl)
  host = parts.netloc.rsplit("@", 1)[-1]
  return urlunsplit(parts._replace(netloc=f"{qaDbUser}:{quote(password, safe='')}@{host}"))


def loadConfig() -> Config:
  databaseUrl = os.getenv("DATABASE_URL")
  if not databaseUrl:
    # 沒有連線字串就啟動，之後每個請求才各自失敗，不如一開始就明講要去哪裡設定
    raise RuntimeError("請在 .env 設定 DATABASE_URL（參考 .env.example）")
  qaPassword = os.getenv("QA_DB_PASSWORD", "").strip()
  return Config(databaseUrl=databaseUrl, qaDatabaseUrl=buildQaDatabaseUrl(databaseUrl, qaPassword) if qaPassword else None)
