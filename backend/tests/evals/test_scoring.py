from decimal import Decimal

from evals.scoring import resultHash, resultsMatch


def testExtraColumnsAreAllowed():
  assert resultsMatch([["林小美"]], [["林小美", "工程部"]])


def testRowOrderDoesNotMatter():
  assert resultsMatch([["a"], ["b"]], [["b"], ["a"]])


def testDuplicateCountMattersUnlessSet():
  assert not resultsMatch([["a"]], [["a"], ["a"]])
  assert resultsMatch([["a"]], [["a"], ["a"]], compareAsSet=True)


def testDifferentValuesFail():
  assert not resultsMatch([["a"]], [["b"]])


def testNullsMatchNulls():
  assert resultsMatch([[None, "2026-11-19T09:00:00"]], [["2026-11-19T09:00:00", None]])
  assert not resultsMatch([[None]], [["事假"]])


def testNumbersAreRoundedAcrossTypes():
  assert resultsMatch([[Decimal("16.000")]], [[16]])
  assert resultsMatch([[2.0 / 3]], [[0.67]])


def testStringsAreStripped():
  assert resultsMatch([["週會 "]], [["週會"]])


def testBothEmptyMatch():
  assert resultsMatch([], [])
  assert not resultsMatch([], [["a"]])
  assert not resultsMatch([["a"]], [])


def testColumnsCannotBeReused():
  # 標準答案兩欄都是同一個值時，模型只給一欄不能算對
  assert not resultsMatch([["a", "a"]], [["a"]])


def testResultHashIgnoresRowOrderButNotContent():
  assert resultHash([[["a"], ["b"]]]) == resultHash([[["b"], ["a"]]])
  assert resultHash([[["a"]]]) != resultHash([[["b"]]])
  assert resultHash([[["a"]], [["b"]]]) != resultHash([[["a"]]])


def testArrayCellsMatchWhenEqual():
  # array_agg 回傳的 list 不能放進 Counter，這裡確認不會 TypeError 且內容相同就算對
  assert resultsMatch([[["a", "b"]]], [[["a", "b"]]])


def testArrayCellsFailWhenDifferent():
  assert not resultsMatch([[["a", "b"]]], [[["a", "c"]]])


def testArrayOrderInsideCellMatters():
  # 陣列是有順序的，不像資料列順序可以任意換
  assert not resultsMatch([[["a", "b"]]], [[["b", "a"]]])


def testNestedListCellsMatch():
  assert resultsMatch([[[["a", Decimal("1.000")], ["b"]]]], [[[["a", 1], ["b"]]]])


def testDictCellsMatchRegardlessOfKeyOrder():
  assert resultsMatch([[{"name": "林小美", "hours": 8}]], [[{"hours": 8.0, "name": "林小美"}]])


def testDictCellsFailWhenValuesDiffer():
  assert not resultsMatch([[{"name": "林小美"}]], [[{"name": "王大明"}]])


def testResultHashHandlesArrayDatetimeAndDecimalCells():
  from datetime import datetime

  rows = [[["a", "b"], datetime(2026, 11, 19, 9, 0), Decimal("16.000")]]
  # 同一組內容、重複計算應得相同結果，且不會因為 list 而爆掉
  assert resultHash([rows]) == resultHash([rows])
  assert resultHash([rows]) != resultHash([[[["b", "a"], datetime(2026, 11, 19, 9, 0), Decimal("16.000")]]])


def testResultHashOnEmptyResultSet():
  assert resultHash([[]]) == resultHash([[]])
  assert resultHash([[]]) != resultHash([])
