import json

import pytest

from app.modules.qa.llm import LlmUnavailableError
from evals import judge
from evals.cases import cases as devCases


def result(caseId="o01", outcome="correct", answer="工程部有陳大文", answerMatch=True, verdict=None):
  return {
    "id": caseId, "outcome": outcome, "answer": answer, "answerMatch": answerMatch, "goldAll": [[["陳大文"]]],
    "judge": None if verdict is None else {"verdict": verdict, "reason": "理由"},
  }


def replyingJudge(*texts, calls=None):
  queue = list(texts)

  def fake(model, messages):
    if calls is not None:
      calls.append(messages)
    reply = queue.pop(0)
    if isinstance(reply, Exception):
      raise reply
    return reply

  return fake


def testParseVerdict():
  assert judge.parseVerdict('{"verdict": "correct", "reason": "有答到"}') == {"verdict": "correct", "reason": "有答到"}


def testParseVerdictWithSurroundingText():
  assert judge.parseVerdict('```json\n{"verdict": "wrong", "reason": "x"}\n```')["verdict"] == "wrong"


def testParseVerdictGarbage():
  assert judge.parseVerdict("我覺得對")["verdict"] == "judgeFailed"
  assert judge.parseVerdict('{"verdict": "maybe"}')["verdict"] == "judgeFailed"


def testJudgeMessagesContainInputs():
  messages = judge.buildJudgeMessages("工程部有哪些人？", [[["工程部"]]], "回答文字甲")
  text = json.dumps(messages, ensure_ascii=False)
  assert "工程部有哪些人？" in text and "工程部" in text and "回答文字甲" in text


def testJudgeSkipsMissingAnswer():
  calls = []
  results = [result(outcome="unavailable", answer=None, answerMatch=None)]
  judge.judgeResults(results, {"o01": "問題"}, "judge-model", replyingJudge(calls=calls))
  assert calls == [] and results[0]["judge"] is None


def testJudgeUnavailableContinues():
  results = [result("o01"), result("o02")]
  callJudge = replyingJudge(LlmUnavailableError("連不上"), '{"verdict": "correct", "reason": "ok"}')
  judge.judgeResults(results, {"o01": "問題甲", "o02": "問題乙"}, "judge-model", callJudge)
  assert results[0]["judge"]["verdict"] == "judgeUnavailable"
  assert results[1]["judge"]["verdict"] == "correct"


def testSummarizeJudge():
  results = [result(verdict="correct"), result(verdict="wrong"), result(verdict="judgeFailed"), result()]
  summary = judge.summarizeJudge(results)
  assert summary["judgeCorrect"] == 1 and summary["judgeScored"] == 2
  assert summary["judgeFailed"] == 1 and summary["judgeUnavailable"] == 0


def testListDisagreements():
  disagree = result("g02", outcome="wrong", answerMatch=True, verdict="correct")
  agree = result("o01", outcome="correct", answerMatch=True, verdict="correct")
  items = judge.listDisagreements([disagree, agree])
  assert [item["id"] for item in items] == ["g02"]
  assert items[0]["sql"] is False and items[0]["judge"] is True


def testStandaloneRejectsTestFile(tmp_path, monkeypatch):
  monkeypatch.setattr(judge, "loadEnvFile", lambda: None)
  path = tmp_path / "test-jev-x.json"
  path.write_text(json.dumps({"split": "test", "correct": 1}), encoding="utf-8")
  with pytest.raises(SystemExit) as raised:
    judge.main([str(path), "--judge", "judge-model"], callJudge=replyingJudge(), models=["judge-model"])
  assert raised.value.code == 1


def testStandaloneWritesJudgedFile(tmp_path, monkeypatch):
  monkeypatch.setattr(judge, "loadEnvFile", lambda: None)
  caseId = devCases[0]["id"]
  path = tmp_path / "dev-jev-x.json"
  path.write_text(json.dumps({"split": "dev", "results": [result(caseId)]}, ensure_ascii=False), encoding="utf-8")
  judge.main([str(path), "--judge", "judge/model"], callJudge=replyingJudge('{"verdict": "correct", "reason": "ok"}'),
             models=["judge/model"])
  saved = json.loads((tmp_path / "dev-jev-x-judged-judge_model.json").read_text(encoding="utf-8"))
  assert saved["results"][0]["judge"]["verdict"] == "correct"
  assert saved["judgeCorrect"] == 1 and saved["judgeModel"] == "judge/model"


def testJudgeRetriesOnceWhenFormatBroken():
  results = [result("o01")]
  callJudge = replyingJudge("我覺得對", '{"verdict": "correct", "reason": "ok"}')
  judge.judgeResults(results, {"o01": "問題"}, "judge-model", callJudge)
  assert results[0]["judge"]["verdict"] == "correct"


def testJudgeFailsAfterSecondBrokenReply():
  results = [result("o01")]
  judge.judgeResults(results, {"o01": "問題"}, "judge-model", replyingJudge("亂講", "還是亂講"))
  assert results[0]["judge"]["verdict"] == "judgeFailed"


def testJudgePromptDefinesOvertimeAndNull():
  system = judge.buildJudgeMessages("問題", [[[None]]], "回答")[0]["content"]
  assert "休息日" in system and "加班" in system
  assert "沒有值" in system
  assert "null 不等於查無資料" in system


def testParseVerdictWithBraceInReason():
  assert judge.parseVerdict('{"verdict": "correct", "reason": "格式 {a} 正確"}')["verdict"] == "correct"


def testParseVerdictKeepsRawWhenBroken():
  assert judge.parseVerdict("完全不是 JSON")["raw"] == "完全不是 JSON"


def testParseVerdictWithTrailingBrace():
  # Gemini 實際回過多一個 } 的 JSON
  assert judge.parseVerdict('{"verdict": "correct", "reason": "有答到"}}')["verdict"] == "correct"


def testFailedCaseWithoutAnswerIsWrong():
  # 使用者看到的是錯誤訊息，不是答案：要算錯，不能從分母消失
  calls = []
  results = [result(outcome="stepsExhausted", answer=None, answerMatch=False)]
  judge.judgeResults(results, {"o01": "問題"}, "judge-model", replyingJudge(calls=calls))
  assert calls == [] and results[0]["judge"]["verdict"] == "wrong"
  assert judge.summarizeJudge(results)["judgeScored"] == 1
