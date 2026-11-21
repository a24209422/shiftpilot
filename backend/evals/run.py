"""跑問答準確率評測。

執行（在 backend/）：python -m evals.run --split dev|test [--model 模型名稱] [--filter 類別或題號] [--update-snapshot]
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from app.infra.db import openDb
from app.infra.errors import AppError
from app.modules.qa import llm as llmModule
from app.modules.qa import service, sqlguard
from evals import gold
from evals.cases import cases as devCases
from evals.cases import categories
from evals.fixture import fixedNow, openEvalWorld
from evals.scoring import resultHash, resultsMatch

outcomes = ("correct", "wrong", "sqlFailed", "blocked", "unavailable")
marks = {"correct": "✅", "wrong": "❌", "sqlFailed": "💥", "blocked": "🚫", "unavailable": "⚠️"}
resultsDir = Path(__file__).parent / "results"
# test 只印進度與總分：每題的對錯和 SQL 看了，就會不自覺地針對那些題目調 prompt
hiddenSplits = {"test"}


def loadCases(split: str) -> list[dict]:
  if split == "dev":
    return devCases
  # 延後匯入：只有真的要跑 test 時才載入，平常不讓 test 題出現在任何輸出或除錯畫面
  from evals.heldout_cases import cases as heldoutCases

  return heldoutCases


def makeCountingLlm(llm):
  def counting(model, messages):
    # 只量 SQL：回答句那次（系統提示不是 SQL 專家）直接回空字串，service 會退回「查到 N 筆資料」
    if "PostgreSQL" not in messages[0]["content"]:
      return ""
    counting.calls += 1
    return llm(model, messages)

  counting.calls = 0
  return counting


class EvalAbortError(Exception):
  pass


def classifyFailure(error: AppError) -> str:
  # 沙盒帳號連不上、問答未設定都是環境問題，不是模型答錯；計分會讓整份結果失真，所以直接中止
  if error.code in ("QA_SANDBOX_UNAVAILABLE", "QA_NOT_CONFIGURED"):
    raise EvalAbortError(f"評測環境有問題（{error.code}）：{error.message}")
  if error.code == "QA_MODEL_UNAVAILABLE":
    return "unavailable"
  if error.code == "QA_QUERY_FAILED":
    try:
      sqlguard.validateSql((error.details or {}).get("sql", ""))
    except sqlguard.UnsafeSqlError:
      return "blocked"
    return "sqlFailed"
  raise error


def evaluateCase(world, case: dict, model: str, llm) -> dict:
  goldResults = gold.runGold(world, case)
  startedAt = time.perf_counter()
  sql, predicted = None, None
  with openDb(world.url) as conn:
    try:
      # 走跟 app 完全相同的 ask（含失敗重試），量到的才是使用者實際會遇到的準確率
      answer = service.ask(conn, world.actors[case["asker"]], case["question"], model, world.qaUrl, fixedNow, llm=llm)
      sql, predicted = answer["sql"], answer["rows"]
      matched = any(resultsMatch(expected, predicted, case.get("compareAsSet", False)) for expected in goldResults)
      outcome = "correct" if matched else "wrong"
    except AppError as error:
      outcome = classifyFailure(error)
      sql = (error.details or {}).get("sql")
  return {
    "id": case["id"], "category": case["category"], "asker": case["asker"], "outcome": outcome, "sql": sql,
    "predicted": predicted, "gold": goldResults[0], "retried": getattr(llm, "calls", 1) > 1,
    "seconds": round(time.perf_counter() - startedAt, 1),
  }


def summarize(split: str, model: str, results: list[dict]) -> dict:
  unavailable = sum(result["outcome"] == "unavailable" for result in results)
  scored = len(results) - unavailable
  correct = sum(result["outcome"] == "correct" for result in results)
  byCategory = {}
  for category in categories:
    inCategory = [result for result in results if result["category"] == category and result["outcome"] != "unavailable"]
    if inCategory:
      byCategory[category] = {"correct": sum(result["outcome"] == "correct" for result in inCategory), "scored": len(inCategory)}
  return {
    "split": split, "model": model, "total": len(results), "scored": scored, "correct": correct, "unavailable": unavailable,
    "score": round(correct / scored, 4) if scored else None, "byCategory": byCategory,
  }


def printCase(out, result: dict) -> None:
  out(f"{marks[result['outcome']]} {result['id']}（{result['asker']}）{' 重試' if result['retried'] else ''} {result['seconds']}s")
  if result["sql"]:
    out("   " + result["sql"].replace("\n", "\n   "))
  if result["outcome"] == "wrong":
    out(f"   標準答案前 5 列：{json.dumps(result['gold'][:5], ensure_ascii=False)}")
    out(f"   模型結果前 5 列：{json.dumps((result['predicted'] or [])[:5], ensure_ascii=False)}")


def saveResults(split: str, model: str, payload: dict) -> Path:
  resultsDir.mkdir(parents=True, exist_ok=True)
  safeModel = "".join(char if char.isalnum() or char in "-." else "_" for char in model)
  path = resultsDir / f"{split}-{safeModel}-{datetime.now():%Y%m%d-%H%M%S}.json"
  path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
  return path


def selectCases(allCases: list[dict], filterText: str | None) -> list[dict]:
  if not filterText:
    return allCases
  return [case for case in allCases if filterText in (case["category"], case["id"])]


def runCases(world, split, model, selected, llm, out) -> dict:
  hidden = split in hiddenSplits
  snapshot = gold.loadSnapshot()
  results = []
  for index, case in enumerate(selected, start=1):
    gold.checkSnapshot(case, gold.runGold(world, case), snapshot)
    result = evaluateCase(world, case, model, makeCountingLlm(llm))
    results.append(result)
    if hidden:
      out(f"{index}/{len(selected)}")
    else:
      printCase(out, result)
  summary = summarize(split, model, results)
  if hidden:
    out(f"總分：{summary['correct']}/{summary['scored']}（模型連不上 {summary['unavailable']} 題不計分）")
    saveResults(split, model, summary)
    return summary
  out("")
  for category, counts in summary["byCategory"].items():
    out(f"{category:6} {counts['correct']}/{counts['scored']}")
  out(f"總分：{summary['correct']}/{summary['scored']}（重試 {sum(result['retried'] for result in results)} 題、模型連不上 {summary['unavailable']} 題）")
  summary["results"] = results
  saveResults(split, model, summary)
  return summary


def runSplit(split, model, filterText=None, llm=llmModule.callModel, out=print, world=None, casesOverride=None) -> dict:
  selected = selectCases(casesOverride if casesOverride is not None else loadCases(split), filterText)
  if world is not None:
    return runCases(world, split, model, selected, llm, out)
  with openEvalWorld() as ownWorld:
    return runCases(ownWorld, split, model, selected, llm, out)


def updateSnapshot(split, world=None, casesOverride=None) -> list[str]:
  selected = casesOverride if casesOverride is not None else loadCases(split)

  def collect(activeWorld):
    return {case["id"]: resultHash(gold.runGold(activeWorld, case)) for case in selected}

  if world is not None:
    hashes = collect(world)
  else:
    with openEvalWorld() as ownWorld:
      hashes = collect(ownWorld)
  gold.saveSnapshot(hashes)
  return sorted(hashes)


def main(argv=None) -> None:
  parser = argparse.ArgumentParser(description="問答準確率評測")
  parser.add_argument("--split", required=True, choices=["dev", "test"])
  parser.add_argument("--model", help="模型名稱，預設 .env 的 OLLAMA_MODEL；必須在模型清單裡")
  parser.add_argument("--filter", help="只跑某個類別或題號（只能用在 dev）")
  parser.add_argument("--update-snapshot", action="store_true", help="重算標準答案快照（確認答案改變是預期的才用）")
  args = parser.parse_args(argv)
  if args.filter and args.split in hiddenSplits:
    parser.error("--filter 只能用在 dev")
  # loadEnv 也會讀 .env 的模型設定，所以先載入再列模型
  from evals.fixture import loadEnv

  loadEnv()
  if args.update_snapshot:
    updated = updateSnapshot(args.split)
    print(f"已更新 {len(updated)} 題的快照")
    return
  models = [item["id"] for item in llmModule.listModels()]
  model = args.model or models[0]
  if model not in models:
    parser.error(f"沒有這個模型：{model}（可用：{', '.join(models)}）")
  try:
    runSplit(args.split, model, args.filter)
  except (gold.GoldSqlError, gold.SnapshotMismatchError, EvalAbortError) as error:
    print(error, file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
  main()
