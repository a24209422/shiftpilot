import json
from decimal import Decimal
from ipaddress import IPv4Address, IPv4Network

import pytest
from psycopg.types.range import Range

from app.modules.qa import sandbox
from app.modules.qa.sandbox import fetchLimited, jsonValue


@pytest.mark.parametrize("value,expected", [
  (float("nan"), "NaN"),
  (float("inf"), "Infinity"),
  (float("-inf"), "-Infinity"),
  (Decimal("NaN"), "NaN"),
  (Decimal("Infinity"), "Infinity"),
  (Decimal("-Infinity"), "-Infinity"),
  (1.5, 1.5),
  (Decimal("2.5"), 2.5),
])
def testNonFiniteNumbersBecomeStrings(value, expected):
  assert jsonValue(value) == expected


@pytest.mark.parametrize("value", [Range(1, 5), IPv4Address("10.0.0.1"), IPv4Network("10.0.0.0/24")])
def testUnknownTypesFallBackToString(value):
  assert jsonValue(value) == str(value)


def testConvertedRowIsStrictJson():
  # Starlette 用 allow_nan=False 序列化回應，這裡要過得了才不會變成 500
  row = jsonValue([float("nan"), Range(1, 5), {"a": Decimal("Infinity")}])
  json.dumps(row, allow_nan=False)


class FakeCursor:
  def __init__(self, rows):
    self.rows = list(rows)
    self.requested = 0

  def fetchmany(self, size):
    batch, self.rows = self.rows[:size], self.rows[size:]
    self.requested += len(batch)
    return batch


def testFetchStopsAtRowCap():
  cursor = FakeCursor([(i,) for i in range(500)])
  rows, truncated = fetchLimited(cursor)
  assert len(rows) == sandbox.maxRows and truncated is True
  # 只多拿一列用來判斷是否還有更多，不會把 500 列都拉回來
  assert cursor.requested <= sandbox.maxRows + sandbox.fetchBatch


def testFetchReturnsEverythingUnderLimits():
  rows, truncated = fetchLimited(FakeCursor([(1, "a"), (2, "b")]))
  assert rows == [[1, "a"], [2, "b"]] and truncated is False


def testFetchStopsAtSizeBudget():
  big = "x" * (sandbox.maxResultChars // 3)
  cursor = FakeCursor([(big,) for _ in range(50)])
  rows, truncated = fetchLimited(cursor)
  assert truncated is True
  assert sum(len(row[0]) for row in rows) <= sandbox.maxResultChars
  # 超過預算就不再往資料庫要下一批
  assert cursor.requested <= len(rows) + sandbox.fetchBatch


def testSingleOversizedValueIsDropped():
  rows, truncated = fetchLimited(FakeCursor([("x" * (sandbox.maxResultChars + 1),)]))
  assert rows == [] and truncated is True
