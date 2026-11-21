"""執行標準答案 SQL 與快照比對。

失敗時只回報題號：psycopg 的錯誤訊息會帶出 SQL 原文，test 題的 SQL 不能因為標準答案出錯而被印出來。
"""
import json
from pathlib import Path

import psycopg

from app.infra.db import openDb
from app.modules.qa import sandbox
from evals.fixture import EvalWorld, fixedNow
from evals.scoring import resultHash

snapshotPath = Path(__file__).parent / "gold_snapshot.json"


class GoldSqlError(Exception):
  def __init__(self, caseIds: list[str]):
    super().__init__(f"標準答案執行失敗，題號：{', '.join(caseIds)}")
    self.caseIds = caseIds


class SnapshotMismatchError(Exception):
  def __init__(self, caseIds: list[str]):
    super().__init__(f"標準答案的結果跟快照不同，題號：{', '.join(caseIds)}（確認答案改變是預期的，才用 --update-snapshot 更新）")
    self.caseIds = caseIds


def loadSnapshot() -> dict[str, str]:
  if not snapshotPath.exists():
    return {}
  return json.loads(snapshotPath.read_text(encoding="utf-8"))


def saveSnapshot(hashes: dict[str, str]) -> None:
  # 保留其他題號：dev 與 test 題共用一份快照，更新一邊不能洗掉另一邊
  merged = {**loadSnapshot(), **hashes}
  snapshotPath.write_text(json.dumps(dict(sorted(merged.items())), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def runGold(world: EvalWorld, case: dict) -> list[list[list]]:
  with openDb(world.url) as conn:
    data = sandbox.collectSandboxData(conn, world.actors[case["asker"]], fixedNow.date())
  results = []
  try:
    with sandbox.openSandbox(world.qaUrl, data) as sandboxConn:
      for sql in [case["goldSql"], *case.get("alsoAccept", [])]:
        _, rows, truncated = sandbox.runQuery(sandboxConn, sql)
        # 標準答案被截斷就無法比對完整結果，當成標準答案寫錯
        if truncated:
          raise GoldSqlError([case["id"]])
        results.append(rows)
  except psycopg.Error:
    # from None：不帶原本的例外，否則 traceback 照樣會印出 SQL
    raise GoldSqlError([case["id"]]) from None
  return results


def checkSnapshot(case: dict, goldResults, snapshot: dict[str, str]) -> None:
  if snapshot.get(case["id"]) != resultHash(goldResults):
    raise SnapshotMismatchError([case["id"]])
