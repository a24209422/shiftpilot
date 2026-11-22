import json
import logging
from datetime import datetime

import httpx
import pytest

from app.modules.qa import jev, prompt
from app.modules.qa.prompt import buildDateReference

fixedNow = datetime(2026, 11, 22, 10, 0)
secretKey = "apikey-secret-1234567890"


@pytest.fixture(autouse=True)
def jevEnv(monkeypatch):
  for name in ("JEV_URL", "JEV_MODEL", "JEV_MIN_CONFIDENCE", "OPENROUTER_API_KEY"):
    monkeypatch.delenv(name, raising=False)
  monkeypatch.setenv("JEV_API_KEY", secretKey)


def goodPayload(tool="find_available_people", probabilities=None, tokens=439):
  probabilities = probabilities if probabilities is not None else {name: (1.0 if name == tool else 0.0) for name in jev.jevOptions}
  return {
    "model": "jev-1.14.0",
    "answers": {"tool": {"type": "choice", "choice": tool, "confidence": 1.0, "probabilities": probabilities}},
    "usage": {"input_tokens": tokens, "output_tokens": 47},
  }


def clientReturning(payload=None, status=200, text=None, calls=None):
  def handler(request):
    if calls is not None:
      calls.append(request)
    if text is not None:
      return httpx.Response(status, text=text)
    return httpx.Response(status, json=payload)

  return httpx.Client(transport=httpx.MockTransport(handler))


def testBuildRequestHasOnlyQuestionDateAndOptions():
  payload = jev.buildJevRequest("下週二下午誰有空？", fixedNow)
  text = json.dumps(payload, ensure_ascii=False)
  assert "下週二下午誰有空？" in payload["state"] and buildDateReference(fixedNow) in payload["state"]
  assert all(option in text for option in jev.jevOptions)
  # 沒有資料表說明或任何資料列
  assert prompt.schemaText not in text and "day_shifts" not in text and "employees" not in text
  assert payload["model"] == "jev-latest"
  assert list(payload["questions"]["tool"]["criteria"]) == jev.jevOptions


def testChoosesHighestOption():
  calls = []
  decision = jev.chooseTool("誰有空", fixedNow, clientReturning(goodPayload(), calls=calls))
  assert decision.tool == "find_available_people"
  assert decision.confidence == 1.0
  assert decision.fallbackReason is None
  assert decision.promptTokens == 439
  assert decision.seconds >= 0
  assert calls[0].url == "https://api.typesafe.ai/v1/systemone"
  assert calls[0].headers["authorization"] == f"Bearer {secretKey}"


def testLowConfidenceFallsBack():
  payload = goodPayload(probabilities={"run_sql": 0.4, "find_available_people": 0.35, "get_busy_periods": 0.25})
  decision = jev.chooseTool("誰有空", fixedNow, clientReturning(payload))
  assert decision.tool is None and decision.fallbackReason == "low_confidence"
  assert decision.confidence == 0.4 and decision.promptTokens == 439


def testMinConfidenceFromEnv(monkeypatch):
  monkeypatch.setenv("JEV_MIN_CONFIDENCE", "0.3")
  payload = goodPayload(probabilities={"run_sql": 0.4, "find_available_people": 0.35, "get_busy_periods": 0.25})
  decision = jev.chooseTool("誰有空", fixedNow, clientReturning(payload))
  assert decision.tool == "run_sql" and decision.fallbackReason is None


@pytest.mark.parametrize("payload", [
  goodPayload(probabilities={"run_sql": 0.1, "drop_table": 0.9, "get_busy_periods": 0.0}),
  {"answers": {"tool": {"type": "choice", "choice": "run_sql"}}, "usage": {"input_tokens": 1}},
  goodPayload(probabilities={"run_sql": "0.9", "find_available_people": 0.1, "get_busy_periods": 0.0}),
  goodPayload(probabilities={"run_sql": 1.5, "find_available_people": 0.0, "get_busy_periods": 0.0}),
  goodPayload(probabilities={}),
  {"answers": {}},
  [],
  "不是物件",
])
def testBadResponses(payload):
  decision = jev.chooseTool("誰有空", fixedNow, clientReturning(payload))
  assert decision.tool is None and decision.fallbackReason == "bad_response"


def testNonJsonBodyIsBadResponse():
  decision = jev.chooseTool("誰有空", fixedNow, clientReturning(text="<html>gateway</html>"))
  assert decision.tool is None and decision.fallbackReason == "bad_response"


@pytest.mark.parametrize("status", [401, 429, 500, 529])
def testHttpErrorFallsBack(status):
  calls = []
  decision = jev.chooseTool("誰有空", fixedNow, clientReturning({"detail": "x"}, status=status, calls=calls))
  assert decision.tool is None and decision.fallbackReason == "unavailable"
  # 不重試
  assert len(calls) == 1


def testTimeoutFallsBack():
  seen = {}

  def handler(request):
    seen["timeout"] = request.extensions["timeout"]
    raise httpx.ReadTimeout("slow", request=request)

  decision = jev.chooseTool("誰有空", fixedNow, httpx.Client(transport=httpx.MockTransport(handler)))
  assert decision.tool is None and decision.fallbackReason == "unavailable"
  assert seen["timeout"]["read"] == 10


def testMasksKeyInLog(caplog):
  client = clientReturning(text=f"bad key {secretKey}", status=401)
  with caplog.at_level(logging.WARNING):
    decision = jev.chooseTool("誰有空", fixedNow, client)
  assert decision.fallbackReason == "unavailable"
  assert secretKey not in caplog.text and "***" in caplog.text


def testApiKeyOnlyFromJevEnv(monkeypatch):
  monkeypatch.delenv("JEV_API_KEY")
  monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-other")
  assert jev.isConfigured() is False
  monkeypatch.setenv("JEV_API_KEY", "  ")
  assert jev.isConfigured() is False


def testCriteriaAreIndependentOfAgentToolDescriptions():
  # Jev 的選項說明可以單獨調整，不能順便改到 agent 模式給 LLM 看的工具說明
  from app.modules.qa import tools

  agentTexts = {item["function"]["name"]: item["function"]["description"] for item in tools.toolDefinitions}
  assert list(jev.jevCriteria) == jev.jevOptions
  assert all(jev.jevCriteria[name] != agentTexts[name] for name in jev.jevOptions)


def testBusyPeriodsCriterionSaysWhatItCannotAnswer():
  text = jev.jevCriteria["get_busy_periods"]
  # 它的欄位只有誰、起訖、種類、標題；要假別、核准狀態、參加者或統計時得用 run_sql
  assert all(word in text for word in ("假別", "核准", "參加者", "run_sql"))
