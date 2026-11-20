import os
from dataclasses import dataclass


@dataclass
class Config:
  databaseUrl: str
  sessionHours: int = 12


def loadConfig() -> Config:
  databaseUrl = os.getenv("DATABASE_URL")
  if not databaseUrl:
    # 沒有連線字串就啟動，之後每個請求才各自失敗，不如一開始就明講要去哪裡設定
    raise RuntimeError("請在 .env 設定 DATABASE_URL（參考 .env.example）")
  return Config(databaseUrl=databaseUrl)
