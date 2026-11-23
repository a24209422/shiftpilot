"""用 LLM 評審判斷最後的回答有沒有答對（回答分數 C）。

兩種用法：
- 評測時一起跑：python -m evals.run --mode agent|jev --judge 模型（test 只能用這種，因為 test 的結果檔不存逐題資料）
- 對已存的 dev 結果重新評審：python -m evals.judge 結果檔 --judge 模型（調評審 prompt 時不用重跑被評的模型）
"""
import argparse
import json
import re
import sys
from pathlib import Path

from app.config import loadEnvFile
from app.modules.qa import llm as llmModule
from evals.cases import cases as devCases

verdicts = ("correct", "wrong")
marks = {True: "✅", False: "❌", None: "－"}

judgeSystemPrompt = """你是問答系統的評審。依照標準答案，判斷助理的回答有沒有正確回答使用者的問題。

規則：
1. 只看回答有沒有答到問題問的事。多提供其他資訊不算錯，但多講的內容跟標準答案矛盾就算錯。
2. 標準答案是資料庫的查詢結果；可能有不只一組可接受的答案，符合其中一組就算對。
3. 標準答案裡的 null 代表提問者沒有權限看這個欄位，回答沒講出這個細節也算對。
4. 標準答案沒有任何資料列，代表正確的回答是「查無資料」。
5. 問的是名單時，回答要包含標準答案裡所有的人或項目，順序不重要。
6. 只輸出一行 JSON，不要其他文字：{"verdict": "correct" 或 "wrong", "reason": "一句話理由"}"""


def buildJudgeMessages(question: str, goldAll: list, answer: str) -> list[dict]:
  goldLines = "\n".join(
    f"第 {index} 組：{json.dumps(rows, ensure_ascii=False, default=str)}" for index, rows in enumerate(goldAll, start=1)
  )
  content = f"問題：{question}\n\n標準答案（可接受的答案共 {len(goldAll)} 組）：\n{goldLines}\n\n助理的回答：{answer}"
  return [{"role": "system", "content": judgeSystemPrompt}, {"role": "user", "content": content}]


def parseVerdict(text: str) -> dict:
  # 模型常把 JSON 包在 ``` 裡或前後多講話，所以只取第一個 {...}
  matched = re.search(r"\{.*?\}", text or "", re.DOTALL)
  try:
    payload = json.loads(matched.group(0)) if matched else None
  except json.JSONDecodeError:
    payload = None
  if not isinstance(payload, dict) or payload.get("verdict") not in verdicts:
    return {"verdict": "judgeFailed", "reason": ""}
  return {"verdict": payload["verdict"], "reason": str(payload.get("reason") or "")}


def judgeResults(results: list[dict], questions: dict[str, str], judgeModel: str, callJudge=None) -> None:
  callJudge = callJudge or llmModule.callModel
  for item in results:
    if item.get("answer") is None:
      item["judge"] = None
      continue
    try:
      reply = callJudge(judgeModel, buildJudgeMessages(questions[item["id"]], item["goldAll"], item["answer"]))
    except llmModule.LlmUnavailableError:
      # 評審連不上不是被評的模型答錯，不計分，整輪繼續跑
      item["judge"] = {"verdict": "judgeUnavailable", "reason": ""}
      continue
    item["judge"] = parseVerdict(reply)


def verdictOf(item: dict) -> bool | None:
  verdict = (item.get("judge") or {}).get("verdict")
  return {"correct": True, "wrong": False}.get(verdict)


def summarizeJudge(results: list[dict]) -> dict:
  verdictList = [(item.get("judge") or {}).get("verdict") for item in results]
  return {
    "judgeCorrect": verdictList.count("correct"), "judgeScored": verdictList.count("correct") + verdictList.count("wrong"),
    "judgeFailed": verdictList.count("judgeFailed"), "judgeUnavailable": verdictList.count("judgeUnavailable"),
  }


def listDisagreements(results: list[dict]) -> list[dict]:
  items = []
  for item in results:
    sqlOk = None if item["outcome"] == "unavailable" else item["outcome"] == "correct"
    marksForCase = {"sql": sqlOk, "answerMatch": item.get("answerMatch"), "judge": verdictOf(item)}
    known = {value for value in marksForCase.values() if value is not None}
    if len(known) > 1:
      items.append({"id": item["id"], **marksForCase, "answer": item.get("answer"), "reason": (item.get("judge") or {}).get("reason")})
  return items


def formatJudgeLines(summary: dict, results: list[dict] | None) -> list[str]:
  """results 是 None 時只印總分（test 用），不印逐題回答與理由。"""
  lines = [
    f"回答（評審）：{summary['judgeCorrect']}/{summary['judgeScored']}"
    f"（格式壞掉 {summary['judgeFailed']} 題、連不上 {summary['judgeUnavailable']} 題）"
  ]
  if results is None:
    return lines
  disagreements = listDisagreements(results)
  lines.append(f"三種分數不一致（SQL／字串比對／評審）：{len(disagreements)} 題")
  for item in disagreements:
    lines.append(f"{item['id']} {marks[item['sql']]}／{marks[item['answerMatch']]}／{marks[item['judge']]}")
    lines.append(f"   回答：{item['answer']}")
    lines.append(f"   評審：{item['reason']}")
  return lines


def safeName(model: str) -> str:
  return "".join(char if char.isalnum() or char in "-." else "_" for char in model)


def main(argv=None, callJudge=None, models=None) -> None:
  parser = argparse.ArgumentParser(description="對已存的 dev 評測結果重新評審回答")
  parser.add_argument("resultsFile")
  parser.add_argument("--judge", required=True, help="評審模型，必須在模型清單裡")
  args = parser.parse_args(argv)
  loadEnvFile()
  models = models if models is not None else [item["id"] for item in llmModule.listModels()]
  if args.judge not in models:
    parser.error(f"沒有這個模型：{args.judge}")
  path = Path(args.resultsFile)
  payload = json.loads(path.read_text(encoding="utf-8"))
  # test 的結果檔本來就沒有逐題資料；就算有，也不能在這裡印出 test 的回答
  if payload.get("split") != "dev" or "results" not in payload:
    print("只能重新評審有逐題資料的 dev 結果檔", file=sys.stderr)
    raise SystemExit(1)
  questions = {case["id"]: case["question"] for case in devCases}
  judgeResults(payload["results"], questions, args.judge, callJudge)
  payload.update(summarizeJudge(payload["results"]), judgeModel=args.judge)
  for line in formatJudgeLines(payload, payload["results"]):
    print(line)
  outPath = path.with_name(f"{path.stem}-judged-{safeName(args.judge)}.json")
  outPath.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
  print(f"結果：{outPath}")


if __name__ == "__main__":
  main()
