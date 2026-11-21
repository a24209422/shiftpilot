from collections import Counter

import pytest

from evals import gold
from evals.cases import cases, categories
from evals.fixture import askerNames, openEvalWorld

quotas = {"org": 5, "shift": 8, "avail": 7, "leave": 8, "meet": 7, "agg": 5}
requiredKeys = {"id", "category", "asker", "question", "goldSql"}


@pytest.fixture(scope="module")
def world():
  with openEvalWorld() as w:
    yield w


def testDevCasesFollowFormatAndQuotas():
  assert categories == list(quotas)
  assert len(cases) == 40
  assert Counter(case["category"] for case in cases) == Counter(quotas)
  assert len({case["id"] for case in cases}) == 40
  for case in cases:
    assert requiredKeys <= set(case), case["id"]
    assert set(case) <= requiredKeys | {"compareAsSet", "alsoAccept"}, case["id"]
    assert case["asker"] in askerNames, case["id"]
  privileged = [case for case in cases if case["asker"] in ("manager", "hr")]
  assert 6 <= len(privileged) <= 10


def testGoldSqlRunsAndMatchesSnapshot(world):
  # 失敗只列題號：test 題用同一套檢查，不能因為檢查失敗印出 SQL
  snapshot = gold.loadSnapshot()
  failed, mismatched, empty = [], [], []
  for case in cases:
    try:
      results = gold.runGold(world, case)
    except gold.GoldSqlError:
      failed.append(case["id"])
      continue
    if not results[0]:
      empty.append(case["id"])
    try:
      gold.checkSnapshot(case, results, snapshot)
    except gold.SnapshotMismatchError:
      mismatched.append(case["id"])
  assert failed == [] and mismatched == []
  # 大部分題目要有資料，否則「模型回空結果」就會被算對
  assert len(empty) <= 4, empty


def testGoldErrorHidesSql(world):
  with pytest.raises(gold.GoldSqlError) as info:
    gold.runGold(world, {"id": "x99", "asker": "employee", "goldSql": "SELECT secret_column FROM employees"})
  assert info.value.caseIds == ["x99"]
  assert "secret_column" not in str(info.value)
  assert info.value.__cause__ is None and info.value.__suppress_context__


def testSnapshotMismatchIsReported():
  with pytest.raises(gold.SnapshotMismatchError):
    gold.checkSnapshot({"id": "x99"}, [[["a"]]], {"x99": "0" * 64})
  with pytest.raises(gold.SnapshotMismatchError):
    gold.checkSnapshot({"id": "x98"}, [[["a"]]], {})


def testHeldoutCasesFollowFormatAndQuotas():
  from evals.heldout_cases import cases as heldout

  heldoutQuotas = {"org": 3, "shift": 5, "avail": 4, "leave": 5, "meet": 4, "agg": 4}
  assert len(heldout) == 25
  assert Counter(case["category"] for case in heldout) == Counter(heldoutQuotas)
  ids = [case["id"] for case in heldout]
  assert len(set(ids)) == 25 and all(caseId.startswith("h-") for caseId in ids)
  assert not set(ids) & {case["id"] for case in cases}
  bad = [case["id"] for case in heldout if not (requiredKeys <= set(case) <= requiredKeys | {"compareAsSet", "alsoAccept"}) or case["asker"] not in askerNames]
  assert bad == []
  privileged = [case for case in heldout if case["asker"] in ("manager", "hr")]
  assert 4 <= len(privileged) <= 6


def testHeldoutGoldRunsAndMatchesSnapshot(world):
  from evals.heldout_cases import cases as heldout

  snapshot = gold.loadSnapshot()
  failed, mismatched, empty = [], [], []
  for case in heldout:
    try:
      results = gold.runGold(world, case)
    except gold.GoldSqlError:
      failed.append(case["id"])
      continue
    if not results[0]:
      empty.append(case["id"])
    try:
      gold.checkSnapshot(case, results, snapshot)
    except gold.SnapshotMismatchError:
      mismatched.append(case["id"])
  assert failed == [] and mismatched == []
  assert len(empty) <= 2, empty
