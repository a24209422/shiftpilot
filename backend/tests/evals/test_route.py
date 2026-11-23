import json

import pytest

from app.modules.qa import jev
from app.modules.qa.jev import JevDecision
from evals import route
from evals.cases import cases as devCases
from evals.fixture import fixedNow
from evals.route_labels import acceptableTools


def caseById(caseId: str) -> dict:
  return next(case for case in devCases if case["id"] == caseId)


def decide(tool, confidence=0.9, fallback=None, tokens=700):
  return lambda question, now: JevDecision(tool, confidence, fallback, tokens, 0.5)


def testLabelsCoverEveryDevCase():
  assert set(acceptableTools) == {case["id"] for case in devCases}
  assert all(tools and tools <= set(jev.jevOptions) for tools in acceptableTools.values())


def testLabelCounts():
  assert acceptableTools["m02"] == {"run_sql"}
  assert acceptableTools["a02"] == {"get_busy_periods", "run_sql"}
  assert sum(tools == {"run_sql"} for tools in acceptableTools.values()) == 32


def testRouteCaseCorrect():
  result = route.routeCase(caseById("o01"), decide("run_sql", 0.9))
  assert result["correct"] is True
  assert result["confidence"] == 0.9


def testRouteCaseWrongTool():
  result = route.routeCase(caseById("m02"), decide("get_busy_periods", 0.8))
  assert result["correct"] is False
  assert result["acceptable"] == ["run_sql"]


def testRouteCaseFallbackIsNotCorrect():
  result = route.routeCase(caseById("o01"), decide(None, 0.3, "low_confidence"))
  assert result["correct"] is False
  assert result["fallback"] == "low_confidence"


def testRouteCasePassesFixedNow():
  calls = []

  def chooseTool(question, now):
    calls.append((question, now))
    return JevDecision("run_sql", 0.9, None, 700, 0.5)

  case = caseById("o01")
  route.routeCase(case, chooseTool)
  assert calls == [(case["question"], fixedNow)]


def routeMany(decisions):
  return [route.routeCase(caseById(caseId), decision) for caseId, decision in decisions]


def testUnavailableCountedSeparately():
  results = routeMany([
    ("o01", decide("run_sql")), ("o02", decide(None, None, "unavailable", None)), ("o03", decide("run_sql")),
  ])
  summary = route.summarizeRoutes(results)
  assert summary["unavailable"] == 1
  assert summary["fallbacks"] == 1
  assert summary["correct"] == 2


def testSummaryToleratesMissingTokens():
  summary = route.summarizeRoutes(routeMany([("o01", decide("run_sql", tokens=700)), ("o02", decide("run_sql", tokens=None))]))
  assert summary["promptTokens"] == 700


def testSummaryEstimatesCost():
  summary = route.summarizeRoutes(routeMany([("o01", decide("run_sql", tokens=1_000_000))]))
  assert summary["estimatedUsd"] == 0.042


def testSummaryHasCriteriaHash():
  value = route.criteriaHash()
  assert len(value) == 8
  assert all(char in "0123456789abcdef" for char in value)
  assert route.criteriaHash() == value
  assert route.summarizeRoutes([])["criteriaHash"] == value


def testSummaryListsWrongIds():
  summary = route.summarizeRoutes(routeMany([("o01", decide("run_sql")), ("m02", decide("get_busy_periods"))]))
  assert summary["wrongIds"] == ["m02"]
  assert summary["total"] == 2


def testMainWithoutKeyExits(monkeypatch, capsys):
  monkeypatch.setattr(route, "loadEnvFile", lambda: None)
  monkeypatch.setattr(jev, "isConfigured", lambda: False)
  with pytest.raises(SystemExit) as raised:
    route.main([])
  assert raised.value.code == 1
  assert "JEV_API_KEY" in capsys.readouterr().err


def testMainRunsEveryDevCaseAndSaves(monkeypatch, tmp_path):
  monkeypatch.setattr(route, "loadEnvFile", lambda: None)
  monkeypatch.setattr(jev, "isConfigured", lambda: True)
  monkeypatch.setattr(route, "resultsDir", tmp_path)
  route.main([], chooseTool=decide("run_sql"))
  saved = list(tmp_path.glob("route-dev-*.json"))
  assert len(saved) == 1
  payload = json.loads(saved[0].read_text(encoding="utf-8"))
  assert [item["id"] for item in payload["results"]] == [case["id"] for case in devCases]
  # 32 題只接受 run_sql，加上 a02、m01 兩題也接受
  assert payload["correct"] == 34
