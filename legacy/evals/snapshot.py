"""標準答案的 hash 快照：改資料表或 fixture 之後，確認受保護的題目答案一題都沒變。

只存題號與 hash，不存資料列：test 題的答案內容不該因為這個檔案而被看到。
重新產生：python -m evals.snapshot
"""
import hashlib
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

import db
from evals import ext_heldout_cases, fixture, heldout_cases, scoring
from evals.cases import cases
from evals.gold import GoldSqlError, runGoldSql

snapshotPath = Path(__file__).parent / "gold_snapshot.json"


class SnapshotMismatchError(Exception):
  def __init__(self, changedIds):
    super().__init__(f"{len(changedIds)} 題的標準答案結果跟快照不同")
    self.changedIds = changedIds


def protectedCases():
  return cases + heldout_cases.heldoutCases + ext_heldout_cases.extHeldoutCases


def hashRows(rows):
  # 標準答案常常沒有 ORDER BY，PostgreSQL 不保證兩次查詢的列順序一樣，所以先排序再算 hash
  normalized = sorted(scoring.normalizeRows(rows), key=repr)
  text = json.dumps(normalized, default=str, ensure_ascii=False)
  return hashlib.sha256(text.encode("utf-8")).hexdigest()


def computeGoldHashes(databaseUrl, caseList):
  hashes, failedIds = {}, []
  for case in caseList:
    sqls = [case["goldSql"], *case.get("alsoAccept", [])]
    try:
      hashes[case["id"]] = [hashRows(runGoldSql(databaseUrl, case["id"], sql)) for sql in sqls]
    except GoldSqlError as error:
      failedIds.extend(error.caseIds)
  if failedIds:
    # 一次列出所有出錯的題號，而且只放題號：錯誤訊息帶出 SQL 的話，test 題的內容就洩漏了
    raise GoldSqlError(failedIds)
  return hashes


def mergeSnapshot(existing, current):
  # 已經在快照裡的題目答案變了，代表改動影響到舊題，這時不能把新結果直接寫進去蓋掉
  changedIds = sorted(caseId for caseId, hashes in current.items() if caseId in existing and existing[caseId] != hashes)
  if changedIds:
    raise SnapshotMismatchError(changedIds)
  merged = {**existing, **current}
  return dict(sorted(merged.items()))


def main():
  load_dotenv()
  testDatabaseUrl = os.getenv("TEST_DATABASE_URL")
  if not testDatabaseUrl:
    print("請在 .env 設定 TEST_DATABASE_URL（參考 .env.example）")
    return 1
  with db.temporarySchema(testDatabaseUrl, "snapshot") as databaseUrl:
    fixture.buildDb(databaseUrl)
    try:
      current = computeGoldHashes(databaseUrl, protectedCases())
    except GoldSqlError as error:
      print(error)
      return 1
  existing = json.loads(snapshotPath.read_text(encoding="utf-8")) if snapshotPath.exists() else {}
  try:
    merged = mergeSnapshot(existing, current)
  except SnapshotMismatchError as error:
    print(f"{error}，沒有寫入快照。題號：{', '.join(error.changedIds)}")
    return 1
  snapshotPath.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
  print(f"快照共 {len(merged)} 題（本次計算 {len(current)} 題）")
  return 0


if __name__ == "__main__":
  sys.exit(main())
