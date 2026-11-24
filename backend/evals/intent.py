"""只量 Jev 判斷意圖的正確率：不開資料庫、不呼叫 LLM，一輪只花 Jev 的錢。

執行（在 backend/）：python -m evals.intent
只跑 dev：查詢題是 cases.py 的 dev 40 題，辦事題在 intent_cases.py。
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime

from app.config import loadEnvFile
from app.modules.qa import intent, jev
from evals import run
from evals.cases import cases as devCases
from evals.fixture import fixedNow
from evals.intent_cases import actionCases

# 每百萬輸入 token 的價格；輸出免費
jevUsdPerMillion = 0.042
resultsDir = run.resultsDir


def allCases() -> list[dict]:
  return [*({"id": case["id"], "question": case["question"], "intent": "query"} for case in devCases), *actionCases]


def intentCase(case: dict, chooseIntent=None, now: datetime = fixedNow) -> dict:
  # 呼叫時才取 intent.chooseIntent，測試才換得掉
  decision = (chooseIntent or intent.chooseIntent)(case["question"], now)
  return {
    "id": case["id"], "question": case["question"], "expected": case["intent"], "chosen": decision.name,
    "confidence": decision.confidence, "fallback": decision.fallbackReason, "correct": decision.name == case["intent"],
    "promptTokens": decision.promptTokens, "seconds": decision.seconds,
  }


def criteriaHash() -> str:
  # 結果檔要認得出是哪一版說明跑的，幾輪下來才分得清
  text = json.dumps(intent.intentCriteria, ensure_ascii=False, sort_keys=True)
  return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def summarizeIntents(results: list[dict]) -> dict:
  promptTokens = sum(item["promptTokens"] or 0 for item in results)
  byIntent = {}
  for item in results:
    group = byIntent.setdefault(item["expected"], {"total": 0, "correct": 0})
    group["total"] += 1
    group["correct"] += item["correct"]
  return {
    "split": "dev", "jevModel": jev.getJevConfig()["model"], "criteriaHash": criteriaHash(),
    "total": len(results), "correct": sum(item["correct"] for item in results), "byIntent": byIntent,
    "fallbacks": sum(item["fallback"] is not None for item in results),
    # 連不上不是說明寫得不好，要另外算，不然會誤判這一版
    "unavailable": sum(item["fallback"] == "unavailable" for item in results),
    "wrongIds": [item["id"] for item in results if not item["correct"]],
    # 查詢被判成辦事會跳出不該有的確認卡，這是最想避免的錯，單獨列出來
    "queryAsAction": sum(item["expected"] == "query" and item["chosen"] not in (None, "query") for item in results),
    "promptTokens": promptTokens, "estimatedUsd": round(promptTokens * jevUsdPerMillion / 1_000_000, 4),
    "finishedAt": datetime.now().isoformat(timespec="seconds"), "results": results,
  }


def formatCase(item: dict) -> str:
  if item["fallback"] is not None:
    return f"↩️ {item['id']} 退回（{item['fallback']}），應為 {item['expected']}"
  line = f"{'✅' if item['correct'] else '❌'} {item['id']} {item['chosen']}（{item['confidence']:.2f}）"
  return line if item["correct"] else f"{line}，應為 {item['expected']}"


def main(argv=None, chooseIntent=None) -> None:
  argparse.ArgumentParser(description="Jev 判斷意圖正確率（只跑 dev）").parse_args(argv)
  loadEnvFile()
  if not jev.isConfigured():
    print("請在 .env 填 JEV_API_KEY", file=sys.stderr)
    raise SystemExit(1)
  results = []
  for case in allCases():
    item = intentCase(case, chooseIntent)
    print(formatCase(item))
    results.append(item)
  summary = summarizeIntents(results)
  groups = "、".join(f"{name} {group['correct']}/{group['total']}" for name, group in summary["byIntent"].items())
  print(
    f"選對 {summary['correct']}/{summary['total']}（{groups}）、查詢被判成辦事 {summary['queryAsAction']} 題、"
    f"退回 {summary['fallbacks']} 題（連不上 {summary['unavailable']} 題）、"
    f"Jev 輸入 {summary['promptTokens']} tokens、約 US${summary['estimatedUsd']}、說明版本 {summary['criteriaHash']}"
  )
  if summary["unavailable"]:
    print("⚠️ 有題目連不上 Jev，這一輪不能拿來比較說明的好壞")
  resultsDir.mkdir(exist_ok=True)
  path = resultsDir / f"intent-dev-{datetime.now():%Y%m%d-%H%M%S}.json"
  path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
  print(f"結果：{path}")


if __name__ == "__main__":
  main()
