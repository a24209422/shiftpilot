"""跑 text2sql 評測。

執行：python -m evals.run [--model 模型名稱] [--filter 類別或題號]
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from functools import partial
from pathlib import Path

from dotenv import load_dotenv

import db
import text2sql
from evals import fixture, scoring
from evals.cases import cases

defaultOutDir = Path(__file__).parent / "results"


def evaluateCase(case, databaseUrl, llm):
  # 有些題目有不只一種合理的答法（見 cases.listTitles），符合其中一種就算對
  acceptedSqls = [case["goldSql"], *case.get("alsoAccept", [])]
  acceptedResults = [db.runReadOnlyQuery(databaseUrl, sql)[1] for sql in acceptedSqls]
  startedAt = time.perf_counter()
  # 走跟 app 完全相同的 answerQuestion（含失敗重試），量到的才是使用者實際會遇到的準確率
  answer = text2sql.answerQuestion(case["question"], databaseUrl, now=fixture.fixedNow, llm=llm)
  seconds = time.perf_counter() - startedAt
  passed = answer["error"] is None and any(
    scoring.resultsMatch(goldRows, answer["rows"], case.get("compareAsSet", False))
    for goldRows in acceptedResults
  )
  return {
    "id": case["id"],
    "category": case["category"],
    "question": case["question"],
    "passed": passed,
    "attempts": answer["attempts"],
    "seconds": round(seconds, 2),
    "goldSql": case["goldSql"],
    "predictedSql": answer["sql"],
    "error": answer["error"],
  }


def summarize(results):
  byCategory = {}
  for result in results:
    stats = byCategory.setdefault(result["category"], {"passed": 0, "total": 0})
    stats["total"] += 1
    stats["passed"] += int(result["passed"])
  passed = sum(stats["passed"] for stats in byCategory.values())
  return {
    "passed": passed,
    "total": len(results),
    "accuracy": round(passed / len(results), 3) if results else 0.0,
    "byCategory": byCategory,
  }


def selectCases(keyword):
  if not keyword:
    return cases
  return [case for case in cases if keyword in (case["category"], case["id"])]


def formatCaseLine(result):
  line = f"{'PASS' if result['passed'] else 'FAIL'} {result['id']} {result['question']} ({result['seconds']}s)"
  if not result["passed"]:
    # 答錯時直接印出模型寫的 SQL，調 prompt 時不用每次都去翻 JSON 報告
    detail = result["error"] or " ".join(result["predictedSql"].split())
    line += f"\n     -> {detail}"
  return line


def formatSummary(summary):
  lines = [f"{category:<10} {stats['passed']}/{stats['total']}" for category, stats in summary["byCategory"].items()]
  lines.append(f"{'total':<10} {summary['passed']}/{summary['total']} ({summary['accuracy']:.1%})")
  return "\n".join(lines)


def writeReport(outDir, model, summary, results):
  outDir.mkdir(parents=True, exist_ok=True)
  # 模型名稱裡的冒號（qwen2.5:3b）不能當 Windows 檔名
  safeModelName = re.sub(r"[^\w.-]", "-", model)
  reportPath = outDir / f"{safeModelName}-{datetime.now():%Y%m%d-%H%M%S}.json"
  report = {"model": model, "fixedNow": fixture.fixedNow.isoformat(), "summary": summary, "results": results}
  reportPath.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
  return reportPath


def main(argv=None, llm=None):
  load_dotenv()
  parser = argparse.ArgumentParser(description="text2sql 評測")
  parser.add_argument("--model", default=text2sql.getOllamaConfig()["model"], help="Ollama 模型名稱")
  parser.add_argument("--filter", default="", help="只跑某個類別或某一題，例如 date 或 d05")
  parser.add_argument("--out", type=Path, default=defaultOutDir, help="報告輸出資料夾")
  args = parser.parse_args(argv)

  selectedCases = selectCases(args.filter)
  if not selectedCases:
    parser.error(f"沒有符合 --filter {args.filter} 的題目")
  testDatabaseUrl = os.getenv("TEST_DATABASE_URL")
  if not testDatabaseUrl:
    parser.error("請在 .env 設定 TEST_DATABASE_URL（參考 .env.example）")
  llm = llm or partial(text2sql.callOllama, model=args.model)
  # 模型寫的 SQL 可能含有終端機編碼印不出來的字元，不能因此讓整輪評測中斷
  sys.stdout.reconfigure(errors="replace")

  results = []
  with db.temporarySchema(testDatabaseUrl, "eval") as databaseUrl:
    fixture.buildDb(databaseUrl)
    for case in selectedCases:
      result = evaluateCase(case, databaseUrl, llm)
      results.append(result)
      print(formatCaseLine(result), flush=True)

  summary = summarize(results)
  print(f"\n模型：{args.model}\n{formatSummary(summary)}")
  print(f"報告：{writeReport(args.out, args.model, summary, results)}")
  return summary


if __name__ == "__main__":
  main()
