"""跑 text2sql 評測。

執行：python -m evals.run [--split dev|test] [--model 模型名稱] [--filter 類別或題號]
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

import db
import text2sql
from evals import fixture, scoring
from evals.cases import cases
from evals.heldout_cases import heldoutCases

defaultOutDir = Path(__file__).parent / "results"
casesBySplit = {"dev": cases, "test": heldoutCases}


def evaluateCase(case, databaseUrl, llm):
  # 有些題目有不只一種合理的答法（見 cases.listTitles），符合其中一種就算對
  acceptedSqls = [case["goldSql"], *case.get("alsoAccept", [])]
  acceptedResults = [db.runReadOnlyQuery(databaseUrl, sql)[1] for sql in acceptedSqls]
  startedAt = time.perf_counter()
  infraError = False
  try:
    # 走跟 app 完全相同的 answerQuestion（含失敗重試），量到的才是使用者實際會遇到的準確率
    answer = text2sql.answerQuestion(case["question"], databaseUrl, now=fixture.fixedNow, llm=llm)
  except requests.RequestException as error:
    # 重試後還是叫不到模型：模型根本沒回答這題，不能算答錯，也不能讓整輪白跑
    infraError = True
    answer = {"sql": "", "rows": [], "error": f"連線錯誤：{error}", "attempts": 0}
  seconds = time.perf_counter() - startedAt
  passed = not infraError and answer["error"] is None and any(
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
    "infraError": infraError,
  }


def summarize(results):
  scoredResults = [result for result in results if not result.get("infraError", False)]
  byCategory = {}
  for result in scoredResults:
    stats = byCategory.setdefault(result["category"], {"passed": 0, "total": 0})
    stats["total"] += 1
    stats["passed"] += int(result["passed"])
  passed = sum(stats["passed"] for stats in byCategory.values())
  return {
    "passed": passed,
    "total": len(scoredResults),
    "accuracy": round(passed / len(scoredResults), 3) if scoredResults else 0.0,
    "byCategory": byCategory,
    "infraErrors": len(results) - len(scoredResults),
  }


def selectCases(keyword, split="dev"):
  pool = casesBySplit[split]
  if not keyword:
    return pool
  return [case for case in pool if keyword in (case["category"], case["id"])]


def formatCaseLine(result):
  if result.get("infraError"):
    return f"ERROR {result['id']} {result['question']} ({result['seconds']}s)\n     -> {result['error']}"
  line =f"{'PASS' if result['passed'] else 'FAIL'} {result['id']} {result['question']} ({result['seconds']}s)"
  if not result["passed"]:
    # 答錯時直接印出模型寫的 SQL，調 prompt 時不用每次都去翻 JSON 報告
    detail = result["error"] or " ".join(result["predictedSql"].split())
    line += f"\n     -> {detail}"
  return line


def formatSummary(summary):
  lines = [f"{category:<10} {stats['passed']}/{stats['total']}" for category, stats in summary["byCategory"].items()]
  lines.append(f"{'total':<10} {summary['passed']}/{summary['total']} ({summary['accuracy']:.1%})")
  if summary.get("infraErrors"):
    lines.append(f"另有 {summary['infraErrors']} 題連線錯誤沒有計分，這輪分數不能跟其他輪比較，請重跑")
  return "\n".join(lines)


def writeReport(outDir, model, split, summary, results):
  outDir.mkdir(parents=True, exist_ok=True)
  # 模型名稱裡的冒號（qwen2.5:3b）不能當 Windows 檔名
  safeModelName = re.sub(r"[^\w.-]", "-", model)
  reportPath = outDir / f"{safeModelName}-{split}-{datetime.now():%Y%m%d-%H%M%S}.json"
  report = {
    "model": model, "split": split, "fixedNow": fixture.fixedNow.isoformat(),
    "summary": summary, "results": results,
  }
  reportPath.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
  return reportPath


def main(argv=None, llm=None):
  load_dotenv()
  parser = argparse.ArgumentParser(description="text2sql 評測")
  parser.add_argument("--split", choices=list(casesBySplit), default="dev", help="dev：調 prompt 用；test：只看分數")
  parser.add_argument(
    "--model", default=text2sql.getOllamaConfig()["model"],
    help="模型名稱：本機 Ollama 模型，或 OPENROUTER_MODELS 裡的雲端模型",
  )
  parser.add_argument("--filter", default="", help="只跑某個類別或某一題，例如 date 或 d05（只限 dev）")
  parser.add_argument("--out", type=Path, default=defaultOutDir, help="報告輸出資料夾")
  args = parser.parse_args(argv)

  provider = text2sql.getProvider(args.model)
  if llm is None and provider != "ollama" and not text2sql.getCloudConfig(provider)["apiKey"]:
    # 沒有 key 就直接停下來：每題都打出 401，跑完只會得到一份全錯的報告
    parser.error(f"請在 .env 設定 {text2sql.cloudProviders[provider]['apiKeyEnv']} 才能評測雲端模型")
  if args.split == "test" and args.filter:
    # 篩出單一題就看得到那題的對錯，等於拿 test 題來調 prompt
    parser.error("test 集不能搭配 --filter")
  selectedCases = selectCases(args.filter, args.split)
  if not selectedCases:
    parser.error(f"沒有符合 --filter {args.filter} 的題目")
  testDatabaseUrl = os.getenv("TEST_DATABASE_URL")
  if not testDatabaseUrl:
    parser.error("請在 .env 設定 TEST_DATABASE_URL（參考 .env.example）")
  llm = llm or text2sql.getLlm(args.model)
  # 模型寫的 SQL 可能含有終端機編碼印不出來的字元，不能因此讓整輪評測中斷
  sys.stdout.reconfigure(errors="replace")

  results = []
  with db.temporarySchema(testDatabaseUrl, "eval") as databaseUrl:
    fixture.buildDb(databaseUrl)
    for index, case in enumerate(selectedCases, start=1):
      result = evaluateCase(case, databaseUrl, llm)
      results.append(result)
      # test 集只印進度，不印每題對錯與 SQL，避免看了之後不自覺地針對 test 題調 prompt
      line = formatCaseLine(result) if args.split == "dev" else f"{index}/{len(selectedCases)}"
      print(line, flush=True)

  summary = summarize(results)
  print(f"\n模型：{args.model}（{args.split}）\n{formatSummary(summary)}")
  print(f"報告：{writeReport(args.out, args.model, args.split, summary, results)}")
  return summary


if __name__ == "__main__":
  main()
