import logging
from datetime import datetime

import httpx
import pytest

from app.modules.qa import assistant, intent, jev

fixedNow = datetime(2026, 11, 22, 10, 0)
secretKey = "apikey-secret-1234567890"


@pytest.fixture(autouse=True)
def jevEnv(monkeypatch):
  for name in ("JEV_URL", "JEV_MODEL", "JEV_MIN_CONFIDENCE"):
    monkeypatch.delenv(name, raising=False)
  monkeypatch.setenv("JEV_API_KEY", secretKey)


def goodPayload(chosen="booking", probabilities=None, tokens=439):
  probabilities = probabilities if probabilities is not None else {name: (1.0 if name == chosen else 0.0) for name in intent.intentNames}
  return {
    "model": "jev-1.14.0",
    "answers": {"intent": {"type": "choice", "choice": chosen, "confidence": 1.0, "probabilities": probabilities}},
    "usage": {"input_tokens": tokens, "output_tokens": 47},
  }


def clientReturning(payload=None, status=200, text=None):
  def handler(request):
    if text is not None:
      return httpx.Response(status, text=text)
    return httpx.Response(status, json=payload)

  return httpx.Client(transport=httpx.MockTransport(handler))


def testIntentToolsAreAssistantTools():
  names = {item["function"]["name"] for item in assistant.assistantToolDefinitions}
  assert list(intent.intentTools) == intent.intentNames
  assert all(set(tools) <= names for tools in intent.intentTools.values())


def testIdToolsHaveRunSql():
  # bookingId、requestId 只有 run_sql 查得到
  assert "run_sql" in intent.intentTools["manageBooking"] and "run_sql" in intent.intentTools["leave"]


def testQueryHasNoProposalTools():
  assert not [name for name in intent.intentTools["query"] if name.startswith("propose_")]


def testQueryCriteriaHasNoActionVerbs():
  assert not [word for word in ("預約", "安排", "改期", "取消", "撤回", "申請") if word in intent.intentCriteria["query"]]


def testRequestHasOnlyQuestionDateAndOptions():
  payload = intent.buildIntentRequest("幫我約林小美開會", fixedNow)
  assert payload["state"] == f"{jev.buildJevDateReference(fixedNow)}\n\n使用者的問題：幫我約林小美開會"
  assert list(payload["questions"]["intent"]["criteria"]) == intent.intentNames
  assert payload["model"] == "jev-latest"


def testChoosesHighestIntent():
  decision = intent.chooseIntent("幫我約會議", fixedNow, clientReturning(goodPayload("booking")))
  assert (decision.name, decision.confidence, decision.fallbackReason, decision.reused, decision.promptTokens) == ("booking", 1.0, None, False, 439)
  assert decision.seconds >= 0


def testLowConfidenceFallsBack():
  payload = goodPayload(probabilities={"query": 0.4, "booking": 0.3, "manageBooking": 0.2, "leave": 0.1})
  decision = intent.chooseIntent("嗯", fixedNow, clientReturning(payload))
  assert decision.name is None and decision.fallbackReason == "low_confidence" and decision.confidence == 0.4


def testUnknownOptionIsBadResponse():
  payload = goodPayload(probabilities={"run_sql": 1.0})
  assert intent.chooseIntent("嗯", fixedNow, clientReturning(payload)).fallbackReason == "bad_response"


def testHttpErrorIsUnavailableAndKeyMasked(caplog):
  with caplog.at_level(logging.WARNING):
    decision = intent.chooseIntent("嗯", fixedNow, clientReturning(status=500, text=f"bad key {secretKey}"))
  assert decision.name is None and decision.fallbackReason == "unavailable"
  assert secretKey not in caplog.text


def testNotConfiguredSkipsHttp(monkeypatch):
  monkeypatch.delenv("JEV_API_KEY")

  def handler(request):
    raise AssertionError("沒設 key 不該呼叫 Jev")

  decision = intent.chooseIntent("嗯", fixedNow, httpx.Client(transport=httpx.MockTransport(handler)))
  assert decision == intent.IntentDecision(None, None, "not_configured", False, None, 0.0)
  assert decision.addedName is None


@pytest.mark.parametrize("name, expected", [(None, None), ("all", None), ("leave", "leave")])
def testToolsFor(name, expected):
  assert intent.toolsFor(name) == (intent.intentTools[expected] if expected else None)
