import json
from datetime import date

import pytest

import db
import text2sql
from evals import cases, fixture, scoring
from evals import run as evalRun


@pytest.mark.parametrize("goldRows, predictedRows", [
  # 完全相同
  ([("週會", "10:00")], [("週會", "10:00")]),
  # 資料列順序不同
  ([("早班",), ("晚班",)], [("晚班",), ("早班",)]),
  # 模型多選了欄位
  ([("週會",)], [("A 會議室", "週會", "2026-11-16 10:00")]),
  # 欄位順序不同
  ([("週會", "A 會議室")], [("A 會議室", "週會")]),
  # 整數與浮點數視為相同
  ([(3,)], [(3.0,)]),
  # 浮點數誤差
  ([(2.5,)], [(2.5000001,)]),
  # 重複的資料列，筆數相同
  ([("早班",), ("早班",)], [("李小華", "早班"), ("林美玲", "早班")]),
])
def testResultsMatchAcceptsEquivalentResults(goldRows, predictedRows):
  assert scoring.resultsMatch(goldRows, predictedRows) is True


@pytest.mark.parametrize("goldRows, predictedRows", [
  # 少一列
  ([("早班",), ("晚班",)], [("早班",)]),
  # 多一列
  ([("早班",)], [("早班",), ("晚班",)]),
  # 缺少標準答案的欄位
  ([("週會", "10:00")], [("週會",)]),
  # 值不同
  ([(3,)], [(4,)]),
  # 重複列的筆數不同
  ([("早班",), ("早班",)], [("早班",)]),
  # 模型查不到資料
  ([("早班",)], []),
  # 每個欄位的值都對得上，但同一列的配對錯了
  ([("王小明", 1), ("李小華", 2)], [("王小明", 2), ("李小華", 1)]),
])
def testResultsMatchRejectsDifferentResults(goldRows, predictedRows):
  assert scoring.resultsMatch(goldRows, predictedRows) is False


def testCompareAsSetIgnoresDuplicateRows():
  goldRows = [("陳大文",)]
  predictedRows = [("陳大文", "晚班", "2026-11-16 16:00"), ("陳大文", "晚班", "2026-11-17 16:00")]

  assert scoring.resultsMatch(goldRows, predictedRows) is False
  assert scoring.resultsMatch(goldRows, predictedRows, compareAsSet=True) is True


def testCompareAsSetStillRejectsDifferentValues():
  assert scoring.resultsMatch([("陳大文",)], [("李小華",)], compareAsSet=True) is False


def testEmptyGoldOnlyMatchesEmptyPrediction():
  assert scoring.resultsMatch([], []) is True
  assert scoring.resultsMatch([], [("早班",)]) is False


@pytest.fixture(scope="module")
def evalDbPath(tmp_path_factory):
  path = tmp_path_factory.mktemp("evals") / "eval.db"
  fixture.buildDb(path)
  return path


def testFixtureBuildsFixedDataset(evalDbPath):
  resourceTypes = [resource["type"] for resource in db.listResources(evalDbPath)]
  _, rows = db.runReadOnlyQuery(evalDbPath, "SELECT COUNT(*), MIN(date(start_at)), MAX(date(start_at)) FROM events")

  assert sorted(resourceTypes) == ["equipment"] * 2 + ["person"] * 4 + ["room"] * 2
  assert rows[0] == (40, "2026-11-09", "2026-11-28")


def testFixtureHasEventsInLastThisAndNextWeek(evalDbPath):
  # 三週都要有資料，相對日期算錯一週時查詢結果才會不一樣
  weekRanges = [(date(2026, 11, 9), date(2026, 11, 15)), (date(2026, 11, 16), date(2026, 11, 22)), (date(2026, 11, 23), date(2026, 11, 29))]

  eventCounts = [len(db.listEvents(evalDbPath, start, end)) for start, end in weekRanges]

  assert eventCounts == [8, 18, 14]


def testCasesHaveUniqueIdsAndCoverEveryCategory():
  caseIds = [case["id"] for case in cases.cases]

  assert len(caseIds) >= 35
  assert len(caseIds) == len(set(caseIds))
  assert {case["category"] for case in cases.cases} == set(cases.categories)


@pytest.mark.parametrize("case", cases.cases, ids=lambda case: case["id"])
def testGoldSqlIsReadOnlyAndReturnsRows(case, evalDbPath):
  text2sql.validateSql(case["goldSql"])
  _, rows = db.runReadOnlyQuery(evalDbPath, case["goldSql"])

  # 標準答案如果查不到資料，模型隨便寫一句查不到資料的 SQL 也會被判定為正確
  assert rows


def testCasesDoNotReuseFewShotQuestions(evalDbPath):
  # 題目如果跟 prompt 裡的範例一樣，模型等於直接看到答案，分數會虛高
  messages = text2sql.buildMessages("問題", db.getSchemaText(), db.getVocabulary(evalDbPath), fixture.fixedNow)
  fewShotQuestions = {message["content"] for message in messages[1:-1] if message["role"] == "user"}

  assert len(fewShotQuestions) > 0
  assert not fewShotQuestions & {case["question"] for case in cases.cases}


def answerWithGoldSql(messages):
  """假的 LLM：每一題都回答標準答案。"""
  goldSqlByQuestion = {case["question"]: case["goldSql"] for case in cases.cases}
  return goldSqlByQuestion[messages[-1]["content"]]


def testEvaluateCasePassesWhenResultMatchesGold(evalDbPath):
  case = cases.cases[0]

  result = evalRun.evaluateCase(case, evalDbPath, answerWithGoldSql)

  assert result["passed"] is True
  assert result["id"] == case["id"]
  assert result["predictedSql"] == case["goldSql"]
  assert result["attempts"] == 1


def testEvaluateCaseFailsWhenResultDiffers(evalDbPath):
  result = evalRun.evaluateCase(cases.cases[0], evalDbPath, lambda messages: "SELECT title FROM events LIMIT 1")

  assert result["passed"] is False
  assert result["error"] is None


def testEvaluateCaseFailsWhenSqlCannotRun(evalDbPath):
  result = evalRun.evaluateCase(cases.cases[0], evalDbPath, lambda messages: "SELECT no_such_column FROM events")

  assert result["passed"] is False
  assert "no_such_column" in result["error"]
  assert result["attempts"] == 2


def testSummarizeCountsByCategory():
  results = [
    {"category": "basic", "passed": True},
    {"category": "basic", "passed": False},
    {"category": "date", "passed": True},
  ]

  summary = evalRun.summarize(results)

  assert summary["passed"] == 2
  assert summary["total"] == 3
  assert summary["accuracy"] == pytest.approx(0.667)
  assert summary["byCategory"] == {"basic": {"passed": 1, "total": 2}, "date": {"passed": 1, "total": 1}}


def testMainRunsFilteredCasesAndWritesReport(tmp_path, capsys):
  summary = evalRun.main(["--filter", "basic", "--model", "fake:1b", "--out", str(tmp_path)], llm=answerWithGoldSql)

  reportPaths = list(tmp_path.glob("fake-1b-*.json"))
  report = json.loads(reportPaths[0].read_text(encoding="utf-8"))
  output = capsys.readouterr().out
  assert summary["passed"] == summary["total"] == 6
  assert len(reportPaths) == 1
  assert report["model"] == "fake:1b"
  assert [result["id"] for result in report["results"]] == ["b01", "b02", "b03", "b04", "b05", "b06"]
  assert "PASS b01" in output
  assert "6/6" in output


def testMainPrintsPredictedSqlForFailedCase(tmp_path, capsys):
  summary = evalRun.main(["--filter", "a01", "--out", str(tmp_path)], llm=lambda messages: "SELECT 1")

  output = capsys.readouterr().out
  assert summary["passed"] == 0
  assert "FAIL a01" in output
  assert "SELECT 1" in output


def testMainRejectsFilterThatMatchesNothing(tmp_path):
  with pytest.raises(SystemExit):
    evalRun.main(["--filter", "no-such-case", "--out", str(tmp_path)], llm=answerWithGoldSql)
