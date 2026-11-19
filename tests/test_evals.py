import io
import json
from datetime import date
from decimal import Decimal

import pytest
import requests
from dotenv import load_dotenv

import db
import text2sql
from evals import cases, fixture, heldout_cases, scoring, snapshot
from evals import run as evalRun

allCases = cases.cases + heldout_cases.heldoutCases


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
  # PostgreSQL 的 numeric 會變成 Decimal，跟浮點數視為相同
  ([(Decimal("2.5000000000000000"),)], [(2.5,)]),
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
def evalDatabaseUrl(testDatabaseUrl):
  # 整個檔案共用一份評測資料：題目只讀不寫，每個測試重建一次太慢
  with db.temporarySchema(testDatabaseUrl, "eval") as url:
    fixture.buildDb(url)
    yield url


def testFixtureBuildsFixedDataset(evalDatabaseUrl):
  resourceTypes = [resource["type"] for resource in db.listResources(evalDatabaseUrl)]
  _, rows = db.runReadOnlyQuery(evalDatabaseUrl, "SELECT COUNT(*), MIN(start_at::date), MAX(start_at::date) FROM events")
  _, detailRows = db.runReadOnlyQuery(evalDatabaseUrl, "SELECT COUNT(*) FROM event_details")

  assert sorted(resourceTypes) == ["equipment"] * 2 + ["person"] * 4 + ["room"] * 2
  assert rows[0] == (35, date(2026, 11, 9), date(2026, 11, 28))
  # 有 5 場會議各有 2 個資源，明細因此比排程多 5 列；統計類題目靠這個差距測出模型有沒有重複計算
  assert detailRows[0] == (40,)


def testFixtureHasEventsInLastThisAndNextWeek(evalDatabaseUrl):
  # 三週都要有資料，相對日期算錯一週時查詢結果才會不一樣
  weekRanges = [(date(2026, 11, 9), date(2026, 11, 15)), (date(2026, 11, 16), date(2026, 11, 22)), (date(2026, 11, 23), date(2026, 11, 29))]

  eventCounts = [len(db.listEvents(evalDatabaseUrl, start, end)) for start, end in weekRanges]

  assert eventCounts == [7, 16, 12]


def testCasesHaveUniqueIdsAndCoverEveryCategory():
  caseIds = [case["id"] for case in cases.cases]

  assert len(caseIds) >= 45
  assert len(caseIds) == len(set(caseIds))
  assert "multi" in cases.categories
  assert {case["category"] for case in cases.cases} == set(cases.categories)


def testHeldoutCasesAreSeparateFromDev():
  heldoutIds = [case["id"] for case in heldout_cases.heldoutCases]
  heldoutQuestions = {case["question"] for case in heldout_cases.heldoutCases}

  assert len(heldoutIds) == len(set(heldoutIds))
  assert not set(heldoutIds) & {case["id"] for case in cases.cases}
  # 跟 dev 同一題的話，調 prompt 時就已經看過答案，不算沒看過的題目
  assert not heldoutQuestions & {case["question"] for case in cases.cases}
  assert {case["category"] for case in heldout_cases.heldoutCases} == set(cases.categories)


@pytest.mark.parametrize("case", allCases, ids=lambda case: case["id"])
def testGoldSqlIsReadOnlyAndReturnsRows(case, evalDatabaseUrl):
  for sql in [case["goldSql"], *case.get("alsoAccept", [])]:
    text2sql.validateSql(sql)
    _, rows = db.runReadOnlyQuery(evalDatabaseUrl, sql)

    # 標準答案如果查不到資料，模型隨便寫一句查不到資料的 SQL 也會被判定為正確
    assert rows


def testCasesDoNotReuseFewShotQuestions(evalDatabaseUrl):
  # 題目如果跟 prompt 裡的範例一樣，模型等於直接看到答案，分數會虛高
  messages = text2sql.buildMessages("問題", db.getLlmSchemaText(), db.getVocabulary(evalDatabaseUrl), fixture.fixedNow)
  fewShotQuestions = {message["content"] for message in messages[1:-1] if message["role"] == "user"}

  assert len(fewShotQuestions) > 0
  assert not fewShotQuestions & {case["question"] for case in allCases}


def answerWithGoldSql(messages):
  """假的 LLM：每一題都回答標準答案。"""
  goldSqlByQuestion = {case["question"]: case["goldSql"] for case in allCases}
  return goldSqlByQuestion[messages[-1]["content"]]


def testEvaluateCasePassesWhenResultMatchesGold(evalDatabaseUrl):
  case = cases.cases[0]

  result = evalRun.evaluateCase(case, evalDatabaseUrl, answerWithGoldSql)

  assert result["passed"] is True
  assert result["id"] == case["id"]
  assert result["predictedSql"] == case["goldSql"]
  assert result["attempts"] == 1


def testEvaluateCaseAcceptsAlternativeAnswer(evalDatabaseUrl):
  # 今天有一場 2 個資源的會議：一場列一次（3 列）或每個資源列一次（4 列）都是合理的回答
  case = {
    "id": "x", "category": "date", "question": "今天有哪些排程？",
    "goldSql": "SELECT title FROM events WHERE start_at::date = '2026-11-17'",
    "alsoAccept": ["SELECT title FROM event_details WHERE start_at::date = '2026-11-17'"],
  }
  wrongSql = "SELECT title FROM events WHERE start_at::date = '2026-11-18'"

  perEvent = evalRun.evaluateCase(case, evalDatabaseUrl, lambda messages: case["goldSql"])
  perResource = evalRun.evaluateCase(case, evalDatabaseUrl, lambda messages: case["alsoAccept"][0])
  wrong = evalRun.evaluateCase(case, evalDatabaseUrl, lambda messages: wrongSql)

  assert perEvent["passed"] is True
  assert perResource["passed"] is True
  assert wrong["passed"] is False


def testEvaluateCaseFailsWhenResultDiffers(evalDatabaseUrl):
  result = evalRun.evaluateCase(cases.cases[0], evalDatabaseUrl, lambda messages: "SELECT title FROM events LIMIT 1")

  assert result["passed"] is False
  assert result["error"] is None


def testEvaluateCaseFailsWhenSqlCannotRun(evalDatabaseUrl):
  result = evalRun.evaluateCase(cases.cases[0], evalDatabaseUrl, lambda messages: "SELECT no_such_column FROM events")

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
  assert report["split"] == "dev"
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


def testMainTestSplitPassesEveryCaseWithGoldAnswers(tmp_path):
  summary = evalRun.main(["--split", "test", "--out", str(tmp_path)], llm=answerWithGoldSql)

  assert summary["passed"] == summary["total"] == len(heldout_cases.heldoutCases)


def testMainTestSplitHidesPerCaseResults(tmp_path, capsys):
  summary = evalRun.main(["--split", "test", "--model", "fake:1b", "--out", str(tmp_path)], llm=lambda messages: "SELECT 1")

  report = json.loads(next(tmp_path.glob("fake-1b-test-*.json")).read_text(encoding="utf-8"))
  output = capsys.readouterr().out
  assert summary["passed"] == 0
  assert report["split"] == "test"
  # 每題的對錯與 SQL 只留在報告檔裡，不印在終端機上
  assert "FAIL" not in output
  assert "SELECT 1" not in output
  assert f"{'total':<10} 0/{len(heldout_cases.heldoutCases)}" in output


def testMainRejectsFilterOnTestSplit(tmp_path):
  with pytest.raises(SystemExit):
    evalRun.main(["--split", "test", "--filter", "basic", "--out", str(tmp_path)], llm=answerWithGoldSql)


def testMainRejectsCloudModelWithoutApiKey(tmp_path, capsys, modelEnv):
  modelEnv(OPENROUTER_MODELS="openai/gpt-6-luna")

  with pytest.raises(SystemExit):
    evalRun.main(["--model", "openai/gpt-6-luna", "--filter", "b01", "--out", str(tmp_path)])

  assert "OPENROUTER_API_KEY" in capsys.readouterr().err
  assert list(tmp_path.iterdir()) == []


def testMainUsesOpenRouterForCloudModel(tmp_path, monkeypatch, modelEnv):
  modelEnv(OPENROUTER_MODELS="openai/gpt-6-luna", OPENROUTER_API_KEY="test-key")
  calledModels = []

  def fakeCallCloudModel(messages, provider, model, apiKey=None):
    calledModels.append((provider, model))
    return "SELECT 1"

  monkeypatch.setattr(text2sql, "callCloudModel", fakeCallCloudModel)

  evalRun.main(["--model", "openai/gpt-6-luna", "--filter", "b01", "--out", str(tmp_path)])

  assert calledModels == [("openrouter", "openai/gpt-6-luna")]
  # 模型名稱的斜線不能變成子資料夾
  assert len(list(tmp_path.glob("openai-gpt-6-luna-dev-*.json"))) == 1


@pytest.mark.parametrize("provider, apiKeyEnv", [("openrouter", "OPENROUTER_API_KEY"), ("google", "GOOGLE_AI_API_KEY")])
def testModelEnvStopsDotenvFromRestoringApiKey(modelEnv, provider, apiKeyEnv):
  # evalRun.main 一開始會執行 load_dotenv()；使用者的 .env 填了 key 之後，測試不能因此拿到真的 key
  load_dotenv(stream=io.StringIO(f"{apiKeyEnv}=real-key"))
  assert text2sql.getCloudConfig(provider)["apiKey"] == ""


def testMainMarksConnectionErrorsWithoutCountingThemWrong(tmp_path, capsys):
  b01Question = next(case["question"] for case in cases.cases if case["id"] == "b01")

  def flakyLlm(messages):
    if messages[-1]["content"] == b01Question:
      raise requests.ConnectionError("連不上")
    return answerWithGoldSql(messages)

  summary = evalRun.main(["--filter", "basic", "--model", "fake:1b", "--out", str(tmp_path)], llm=flakyLlm)

  report = json.loads(next(tmp_path.glob("fake-1b-*.json")).read_text(encoding="utf-8"))
  output = capsys.readouterr().out
  # 沒被模型回答的題目不算答錯，也不算進題數，報告照樣寫出來
  assert summary["passed"] == summary["total"] == 5
  assert summary["infraErrors"] == 1
  assert summary["byCategory"]["basic"] == {"passed": 5, "total": 5}
  assert [result["id"] for result in report["results"] if result["infraError"]] == ["b01"]
  assert "ERROR b01" in output
  assert "另有 1 題連線錯誤沒有計分" in output


def testMainRejectsGoogleModelWithoutApiKey(tmp_path, capsys, modelEnv):
  modelEnv(GOOGLE_AI_MODELS="gemini-3.5-flash-lite")

  with pytest.raises(SystemExit):
    evalRun.main(["--model", "gemini-3.5-flash-lite", "--filter", "b01", "--out", str(tmp_path)])

  assert "GOOGLE_AI_API_KEY" in capsys.readouterr().err
  assert list(tmp_path.iterdir()) == []


def testEvaluateCaseKeepsResponseBodyOfConnectionError(evalDatabaseUrl):
  response = requests.Response()
  response.status_code = 404
  response._content = '{"error": {"message": "models/gemini-x is not found"}}'.encode("utf-8")

  def failingLlm(messages):
    raise requests.HTTPError("404 Client Error: Not Found for url: https://example.test", response=response)

  result = evalRun.evaluateCase(cases.cases[0], evalDatabaseUrl, failingLlm)

  # HTTPError 的字串只有狀態和網址；模型 ID 打錯或 key 無效時，原因只在回應內文裡
  assert result["infraError"] is True
  assert "models/gemini-x is not found" in result["error"]


def testHashRowsIgnoresRowOrder():
  assert snapshot.hashRows([("早班", 1), ("晚班", 2)]) == snapshot.hashRows([("晚班", 2), ("早班", 1)])
  assert snapshot.hashRows([("早班",)]) != snapshot.hashRows([("晚班",)])


def testMergeSnapshotAddsNewIds():
  merged = snapshot.mergeSnapshot({"b01": ["aa"]}, {"b01": ["aa"], "h-org01": ["bb"]})

  assert merged == {"b01": ["aa"], "h-org01": ["bb"]}


def testMergeSnapshotRefusesChangedHash():
  with pytest.raises(snapshot.SnapshotMismatchError) as error:
    snapshot.mergeSnapshot({"b01": ["aa"], "b02": ["cc"]}, {"b01": ["zz"], "b02": ["cc"]})

  assert error.value.changedIds == ["b01"]


def testGoldAnswersMatchSnapshot(evalDatabaseUrl):
  # 只比 hash：失敗時只看得到題號，看不到 test 的答案內容
  saved = json.loads(snapshot.snapshotPath.read_text(encoding="utf-8"))

  assert snapshot.computeGoldHashes(evalDatabaseUrl, snapshot.protectedCases()) == saved


overlappingApprovedLeaveSql = """
  SELECT l.id FROM leave_requests l
  JOIN employees em ON em.id = l.employee_id
  JOIN event_resources er ON er.resource_id = em.resource_id
  JOIN events e ON e.id = er.event_id
  WHERE l.status = 'approved' AND e.start_at < l.end_at AND e.end_at > l.start_at
"""


def queryScalar(databaseUrl, sql):
  return db.runReadOnlyQuery(databaseUrl, sql)[1][0][0]


def testFixtureOrganizationDescribesOnlyExistingResources(evalDatabaseUrl):
  # 新增資源會讓「列出所有會議室」這類舊題的答案變動，所以新表只能描述現有的資源
  _, employeeTypes = db.runReadOnlyQuery(evalDatabaseUrl, "SELECT r.type FROM employees e JOIN resources r ON r.id = e.resource_id")
  _, roomTypes = db.runReadOnlyQuery(evalDatabaseUrl, "SELECT r.type FROM rooms JOIN resources r ON r.id = rooms.resource_id")

  assert [row[0] for row in employeeTypes] == ["person"] * 4
  assert [row[0] for row in roomTypes] == ["room"] * 2


def testFixtureOrganizationHasTwoLevelsOfManagers(evalDatabaseUrl):
  assert queryScalar(evalDatabaseUrl, "SELECT COUNT(*) FROM employees WHERE manager_id IS NULL") == 1
  assert queryScalar(evalDatabaseUrl, """
    SELECT COUNT(*) FROM employees e JOIN employees m ON m.id = e.manager_id WHERE m.manager_id IS NOT NULL
  """) >= 1
  assert queryScalar(evalDatabaseUrl, "SELECT COUNT(*) FROM departments") == 3
  assert queryScalar(evalDatabaseUrl, """
    SELECT COUNT(*) FROM departments WHERE parent_id = (SELECT id FROM departments WHERE parent_id IS NULL)
  """) == 2


def testFixtureRoomsDiffer(evalDatabaseUrl):
  # 兩間要有差異，「容納 8 人以上」「有視訊」這類題目才篩得出不同結果
  assert queryScalar(evalDatabaseUrl, "SELECT COUNT(DISTINCT floor) FROM rooms") == 2
  assert queryScalar(evalDatabaseUrl, "SELECT COUNT(DISTINCT capacity) FROM rooms") == 2
  assert queryScalar(evalDatabaseUrl, "SELECT COUNT(DISTINCT has_video_conference) FROM rooms") == 2


def testFixtureLeaveRequestsCoverEveryStatusAndType(evalDatabaseUrl):
  _, statusRows = db.runReadOnlyQuery(evalDatabaseUrl, "SELECT DISTINCT status FROM leave_requests")
  _, typeRows = db.runReadOnlyQuery(evalDatabaseUrl, "SELECT DISTINCT leave_type FROM leave_requests")

  assert {row[0] for row in statusRows} == {"pending", "approved", "rejected"}
  assert {row[0] for row in typeRows} == {"annual", "sick", "personal"}
  assert queryScalar(evalDatabaseUrl, "SELECT COUNT(*) FROM leave_requests WHERE end_at::date > start_at::date") >= 1
  assert queryScalar(evalDatabaseUrl, "SELECT COUNT(*) FROM leave_requests WHERE end_at - start_at <= interval '4 hours'") >= 1


def testFixtureApprovedLeaveDoesNotOverlapOwnEvents(evalDatabaseUrl):
  assert db.runReadOnlyQuery(evalDatabaseUrl, overlappingApprovedLeaveSql)[1] == []


def testFixtureWorkHoursOnlyForStaffWithoutShifts(evalDatabaseUrl):
  # 輪班的員工上班時間看 events 裡的 shift；兩邊都有資料的話，「幾點上班」會有兩個答案
  _, rows = db.runReadOnlyQuery(evalDatabaseUrl, """
    SELECT DISTINCT em.id FROM work_hours w
    JOIN employees em ON em.id = w.employee_id
    JOIN event_resources er ON er.resource_id = em.resource_id
    JOIN events e ON e.id = er.event_id
    WHERE e.category = 'shift'
  """)

  assert queryScalar(evalDatabaseUrl, "SELECT COUNT(*) FROM work_hours") > 0
  assert rows == []


def testFixtureHolidays(evalDatabaseUrl):
  assert queryScalar(evalDatabaseUrl, """
    SELECT COUNT(*) FROM holidays h
    WHERE h.day BETWEEN '2026-11-09' AND '2026-11-28'
      AND NOT EXISTS (SELECT 1 FROM events e WHERE e.start_at::date = h.day)
  """) >= 1
  assert queryScalar(evalDatabaseUrl, "SELECT COUNT(*) FROM holidays WHERE day > '2026-11-28'") >= 1
