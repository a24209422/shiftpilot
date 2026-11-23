from datetime import date, datetime
from decimal import Decimal

from evals.answer_match import matchAnswer


def testNoneAnswer():
  assert matchAnswer(None, [[["工程部"]]]) is None


def testNamesAllPresent():
  assert matchAnswer("有陳大文、林小美", [[["陳大文"], ["林小美"]]]) is True


def testMissingName():
  assert matchAnswer("只有陳大文", [[["陳大文"], ["林小美"]]]) is False


def testAnyAlternative():
  assert matchAnswer("共 2 場", [[[3]], [[2]]]) is True


def testNumberNormalized():
  assert matchAnswer("平均 3.2 人", [[[Decimal("3.20")]]]) is True


def testWholeFloat():
  assert matchAnswer("工程部 68 小時", [[["工程部", 68.0]]]) is True


def testNumberNeedsBoundary():
  assert matchAnswer("11/17 有會議", [[[1]]]) is False


def testDateForms():
  for answer in ("11/17 放假", "11 月 17 日放假", "11月17日放假", "2026-11-17 放假"):
    assert matchAnswer(answer, [[["2026-11-17"]]]) is True
  assert matchAnswer("11月17日放假", [[[date(2026, 11, 17)]]]) is True
  assert matchAnswer("11/18 放假", [[["2026-11-17"]]]) is False


def testDateTimeNeedsTime():
  assert matchAnswer("11/24 10:00 開會", [[["2026-11-24T10:00:00"]]]) is True
  assert matchAnswer("11月24日 10點開會", [[[datetime(2026, 11, 24, 10, 0)]]]) is True
  assert matchAnswer("11/24 開會", [[["2026-11-24T10:00:00"]]]) is False


def testSkipsNoneAndBool():
  assert matchAnswer("林小美請假", [[["林小美", None, True]]]) is True


def testEmptyGold():
  assert matchAnswer("查無資料", [[]]) is True
  assert matchAnswer("這週沒有人請假", [[]]) is True
  assert matchAnswer("有 3 筆", [[]]) is False
