"""只量 Jev 選工具的正確率：不開資料庫、不呼叫 LLM，一輪只花 Jev 的錢。

執行（在 backend/）：python -m evals.route
只跑 dev；test 只能用 python -m evals.run 看總分。
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime

from app.config import loadEnvFile
from app.modules.qa import jev
from evals import run
from evals.cases import cases as devCases
from evals.fixture import fixedNow
from evals.route_labels import acceptableTools

# 每百萬輸入 token 的價格；輸出免費
jevUsdPerMillion = 0.042
resultsDir = run.resultsDir


def routeCase(case: dict, chooseTool=None, now: datetime = fixedNow) -> dict:
  # 呼叫時才取 jev.chooseTool，測試才換得掉
  decision = (chooseTool or jev.chooseTool)(case["question"], now)
  acceptable = acceptableTools[case["id"]]
  return {
    "id": case["id"], "question": case["question"], "acceptable": sorted(acceptable),
    "routeTool": decision.tool, "confidence": decision.confidence, "fallback": decision.fallbackReason,
    "correct": decision.tool in acceptable, "promptTokens": decision.promptTokens, "seconds": decision.seconds,
  }


def criteriaHash() -> str:
  # 結果檔要認得出是哪一版說明跑的，幾輪下來才分得清
  text = json.dumps(jev.jevCriteria, ensure_ascii=False, sort_keys=True)
  return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def summarizeRoutes(results: list[dict]) -> dict:
  promptTokens = sum(item["promptTokens"] or 0 for item in results)
  return {
    "split": "dev", "jevModel": jev.getJevConfig()["model"], "criteriaHash": criteriaHash(),
    "total": len(results), "correct": sum(item["correct"] for item in results),
    "fallbacks": sum(item["fallback"] is not None for item in results),
    # 連不上不是說明寫得不好，要另外算，不然會誤判這一版
    "unavailable": sum(item["fallback"] == "unavailable" for item in results),
    "wrongIds": [item["id"] for item in results if not item["correct"]],
    "promptTokens": promptTokens, "estimatedUsd": round(promptTokens * jevUsdPerMillion / 1_000_000, 4),
    "finishedAt": datetime.now().isoformat(timespec="seconds"), "results": results,
  }


def formatCase(item: dict) -> str:
  if item["fallback"] is not None:
    return f"↩️ {item['id']} 退回（{item['fallback']}）"
  line = f"{'✅' if item['correct'] else '❌'} {item['id']} {item['routeTool']}（{item['confidence']:.2f}）"
  return line if item["correct"] else f"{line}，可接受：{'、'.join(item['acceptable'])}"


def main(argv=None, chooseTool=None) -> None:
  argparse.ArgumentParser(description="Jev 選工具正確率（只跑 dev）").parse_args(argv)
  loadEnvFile()
  if not jev.isConfigured():
    print("請在 .env 填 JEV_API_KEY", file=sys.stderr)
    raise SystemExit(1)
  results = []
  for case in devCases:
    item = routeCase(case, chooseTool)
    print(formatCase(item))
    results.append(item)
  summary = summarizeRoutes(results)
  print(
    f"選對 {summary['correct']}/{summary['total']}、退回 {summary['fallbacks']} 題（連不上 {summary['unavailable']} 題）、"
    f"Jev 輸入 {summary['promptTokens']} tokens、約 US${summary['estimatedUsd']}、說明版本 {summary['criteriaHash']}"
  )
  if summary["unavailable"]:
    print("⚠️ 有題目連不上 Jev，這一輪不能拿來比較說明的好壞")
  resultsDir.mkdir(exist_ok=True)
  path = resultsDir / f"route-dev-{datetime.now():%Y%m%d-%H%M%S}.json"
  path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
  print(f"結果：{path}")


if __name__ == "__main__":
  main()
