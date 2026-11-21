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
