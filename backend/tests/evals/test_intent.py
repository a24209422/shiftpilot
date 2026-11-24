import json

import pytest

from app.modules.qa import jev
from app.modules.qa.intent import IntentDecision
from evals import intent as intentEval
from evals.cases import cases as devCases
from evals.fixture import fixedNow
from evals.intent_cases import actionCases


def caseById(caseId: str) -> dict:
  return next(case for case in intentEval.allCases() if case["id"] == caseId)


def decide(name, confidence=0.9, fallback=None, tokens=500):
  return lambda question, now: IntentDecision(name, confidence, fallback, False, tokens, 0.3)


def testAllCasesLabelDevAsQuery():
  cases = intentEval.allCases()
  assert [case["id"] for case in cases[:len(devCases)]] == [case["id"] for case in devCases]
  assert all(case["intent"] == "query" for case in cases[:len(devCases)])
  assert cases[len(devCases):] == actionCases


def testActionCaseCounts():
  ids = [case["id"] for case in actionCases]
  assert len(ids) == len(set(ids)) and not set(ids) & {case["id"] for case in devCases}
  for name, prefix in (("booking", "ib"), ("manageBooking", "im"), ("leave", "il")):
    group = [case for case in actionCases if case["intent"] == name]
    assert len(group) == 8 and all(case["id"].startswith(prefix) for case in group)
  devQuestions = {case["question"] for case in devCases}
  assert not [case for case in actionCases if case["question"] in devQuestions]


def testIntentCaseCorrectAndWrong():
  right = intentEval.intentCase(caseById("ib01"), decide("booking"))
  wrong = intentEval.intentCase(caseById("ib01"), decide("query"))
  assert right["correct"] is True and right["expected"] == "booking" and right["chosen"] == "booking"
  assert wrong["correct"] is False and wrong["chosen"] == "query"


def testFallbackIsNotCorrect():
  result = intentEval.intentCase(caseById("o01"), decide(None, 0.3, "low_confidence"))
  assert result["correct"] is False and result["fallback"] == "low_confidence"


def testIntentCasePassesFixedNow():
  calls = []

  def chooseIntent(question, now):
    calls.append((question, now))
    return IntentDecision("query", 0.9, None, False, 500, 0.3)

  case = caseById("o01")
  intentEval.intentCase(case, chooseIntent)
  assert calls == [(case["question"], fixedNow)]


def testSummaryCountsQueryAsAction():
  results = [
    intentEval.intentCase(caseById("o01"), decide("booking")),
    intentEval.intentCase(caseById("o02"), decide("query")),
    intentEval.intentCase(caseById("ib01"), decide("query")),
  ]
  summary = intentEval.summarizeIntents(results)
  # 查詢題被判成辦事才算；辦事題被判成查詢另外看 byIntent
  assert summary["queryAsAction"] == 1 and summary["correct"] == 1 and summary["wrongIds"] == ["o01", "ib01"]
  assert summary["byIntent"]["query"] == {"total": 2, "correct": 1}
  assert summary["byIntent"]["booking"] == {"total": 1, "correct": 0}


def testUnavailableCountedSeparately():
  results = [
    intentEval.intentCase(caseById("o01"), decide("query")),
    intentEval.intentCase(caseById("o02"), decide(None, None, "unavailable", None)),
  ]
  summary = intentEval.summarizeIntents(results)
  assert summary["unavailable"] == 1 and summary["fallbacks"] == 1 and summary["promptTokens"] == 500


def testSummaryEstimatesCostAndHash():
  summary = intentEval.summarizeIntents([intentEval.intentCase(caseById("o01"), decide("query", tokens=1_000_000))])
  assert summary["estimatedUsd"] == 0.042 and len(summary["criteriaHash"]) == 8


def testMainWithoutKeyExits(monkeypatch, capsys):
  monkeypatch.setattr(intentEval, "loadEnvFile", lambda: None)
  monkeypatch.setattr(jev, "isConfigured", lambda: False)
  with pytest.raises(SystemExit) as raised:
    intentEval.main([])
  assert raised.value.code == 1 and "JEV_API_KEY" in capsys.readouterr().err


def testMainRunsEveryCaseAndSaves(monkeypatch, tmp_path):
  monkeypatch.setattr(intentEval, "loadEnvFile", lambda: None)
  monkeypatch.setattr(jev, "isConfigured", lambda: True)
  monkeypatch.setattr(intentEval, "resultsDir", tmp_path)
  intentEval.main([], chooseIntent=decide("query"))
  saved = list(tmp_path.glob("intent-dev-*.json"))
  assert len(saved) == 1
  payload = json.loads(saved[0].read_text(encoding="utf-8"))
  assert [item["id"] for item in payload["results"]] == [case["id"] for case in intentEval.allCases()]
  assert payload["correct"] == len(devCases) and payload["queryAsAction"] == 0
