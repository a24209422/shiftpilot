import pytest

from app.modules.qa import jev
from app.modules.qa.jev import JevDecision
from app.modules.qa.llm import LlmUnavailableError, ToolCall, ToolReply
from evals import gold, run
from evals.fixture import openEvalWorld

miniCases = [
  {"id": "t01", "category": "org", "asker": "employee", "question": "工程部有哪些人？",
   "goldSql": "SELECT e.name FROM employees e JOIN departments d ON d.id = e.department_id WHERE d.name = '工程部'", "compareAsSet": True},
  {"id": "t02", "category": "leave", "asker": "employee", "question": "林小美請什麼假？",
   "goldSql": "SELECT r.leave_type FROM leave_requests r JOIN employees e ON e.id = r.employee_id WHERE e.name = '林小美' AND r.status = 'approved'"},
]


@pytest.fixture(scope="module")
def world():
  with openEvalWorld() as w:
    yield w


@pytest.fixture(autouse=True)
def localModel(monkeypatch, tmp_path):
  monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:3b")
  for name in ("LOCAL_MODELS", "OPENROUTER_API_KEY", "GOOGLE_AI_API_KEY"):
    monkeypatch.setenv(name, "")
  # 快照與結果檔都寫到暫存目錄，測試不碰正式的 gold_snapshot.json
  monkeypatch.setattr(gold, "snapshotPath", tmp_path / "snapshot.json")
  monkeypatch.setattr(run, "resultsDir", tmp_path / "results")


def replying(sqlByQuestion):
  def fake(model, messages):
    return f"```sql\n{sqlByQuestion[messages[-1]['content']]}\n```"
  return fake


def evaluate(world, sql, case=miniCases[0]):
  return run.evaluateCase(world, case, "qwen2.5:3b", run.makeCountingLlm(lambda model, messages: sql))


def testCorrectWithExtraColumnsAndOrder(world):
  result = evaluate(world, "SELECT e.name, e.job_title FROM employees e WHERE e.department_id = (SELECT id FROM departments WHERE name = '工程部') ORDER BY e.name DESC")
  assert result["outcome"] == "correct" and result["retried"] is False


def testWrongResult(world):
  assert evaluate(world, "SELECT name FROM employees")["outcome"] == "wrong"


def testSqlFailedAfterRetry(world):
  result = evaluate(world, "SELECT nope FROM employees")
  assert result["outcome"] == "sqlFailed" and result["retried"] is True


def testBlocked(world):
  assert evaluate(world, "SELECT set_config('role', 'x', false)")["outcome"] == "blocked"


def testUnavailableIsNotScored(world):
  def down(model, messages):
    raise LlmUnavailableError("無法呼叫 Ollama")

  gold.saveSnapshot({case["id"]: gold.resultHash(gold.runGold(world, case)) for case in miniCases})
  summary = run.runSplit("dev", "qwen2.5:3b", llm=down, world=world, casesOverride=miniCases)
  assert summary["unavailable"] == 2 and summary["scored"] == 0 and summary["score"] is None


def testNullAnswerForEmployeeIsCorrect(world):
  sql = "SELECT leave_type FROM leave_requests WHERE employee_id = (SELECT id FROM employees WHERE name = '林小美') AND status = 'approved'"
  assert evaluate(world, sql, miniCases[1])["outcome"] == "correct"


def testAnswerCallIsSkipped(world):
  seen = []

  def fake(model, messages):
    seen.append(messages[0]["content"])
    return "SELECT name FROM employees"

  run.evaluateCase(world, miniCases[0], "qwen2.5:3b", run.makeCountingLlm(fake))
  assert len(seen) == 1 and "PostgreSQL" in seen[0]


def testDevSummaryAndJson(world):
  gold.saveSnapshot({case["id"]: gold.resultHash(gold.runGold(world, case)) for case in miniCases})
  llm = replying({case["question"]: case["goldSql"] for case in miniCases})
  lines = []
  summary = run.runSplit("dev", "qwen2.5:3b", llm=llm, out=lines.append, world=world, casesOverride=miniCases)
  assert summary["correct"] == 2 and summary["score"] == 1.0
  assert summary["byCategory"]["org"] == {"correct": 1, "scored": 1}
  assert any("t01" in line for line in lines)
  assert len(list((run.resultsDir).glob("dev-*.json"))) == 1


def testTestSplitPrintsOnlyProgressAndTotal(world):
  gold.saveSnapshot({case["id"]: gold.resultHash(gold.runGold(world, case)) for case in miniCases})
  llm = replying({case["question"]: case["goldSql"] for case in miniCases})
  lines = []
  summary = run.runSplit("test", "qwen2.5:3b", llm=llm, out=lines.append, world=world, casesOverride=miniCases)
  text = "\n".join(lines)
  for case in miniCases:
    assert case["id"] not in text and case["question"] not in text and case["goldSql"] not in text
  assert "results" not in summary and summary["correct"] == 2
  saved = next((run.resultsDir).glob("test-*.json")).read_text(encoding="utf-8")
  assert "t01" not in saved and "SELECT" not in saved


def testSnapshotMismatchStopsRun(world):
  gold.saveSnapshot({"t01": "0" * 64, "t02": "0" * 64})
  with pytest.raises(gold.SnapshotMismatchError) as info:
    run.runSplit("dev", "qwen2.5:3b", llm=lambda model, messages: "", world=world, casesOverride=miniCases)
  assert info.value.caseIds == ["t01", "t02"]


def testUpdateSnapshot(world):
  assert run.updateSnapshot("dev", world=world, casesOverride=miniCases) == ["t01", "t02"]
  assert set(gold.loadSnapshot()) == {"t01", "t02"}


def testFilterOnlyForDev():
  with pytest.raises(SystemExit):
    run.main(["--split", "test", "--filter", "org"])


def testUnknownModelIsRejected(monkeypatch):
  # 不依賴 .env：loadEnv 換成空操作，模型清單由 OLLAMA_MODEL 決定
  monkeypatch.setattr("evals.fixture.loadEnv", lambda: ("", ""))
  with pytest.raises(SystemExit) as info:
    run.main(["--split", "dev", "--model", "gpt-x"])
  assert info.value.code == 2


def testSandboxUnavailableAbortsInsteadOfScoring(world, monkeypatch):
  from app.infra.errors import AppError

  def broken(*args, **kwargs):
    raise AppError("QA_SANDBOX_UNAVAILABLE", "問答沙盒帳號連不上", 503)

  monkeypatch.setattr(run.service, "ask", broken)
  with pytest.raises(run.EvalAbortError):
    evaluate(world, "SELECT 1")


hiddenCases = [
  {"id": "h01", "category": "org", "asker": "employee", "question": "秘密問題甲？",
   "goldSql": "SELECT e.name FROM employees e WHERE e.name = '林小美'"},
  {"id": "h02", "category": "org", "asker": "employee", "question": "秘密問題乙？", "goldSql": "SELECT e.name FROM employees e WHERE e.name = '陳大文'"},
  {"id": "h03", "category": "org", "asker": "employee", "question": "秘密問題丙？", "goldSql": "SELECT e.name FROM employees e WHERE e.name = '黃志強'"},
  {"id": "h04", "category": "org", "asker": "employee", "question": "秘密問題丁？", "goldSql": "SELECT e.name FROM employees e WHERE e.name = '王建國'"},
  {"id": "h05", "category": "org", "asker": "employee", "question": "秘密問題戊？", "goldSql": "SELECT e.name FROM employees e WHERE e.name = '劉怡君'"},
]
# 平均秒數、工具次數、token 總和都是整份的彙總，不會帶出單題內容
allowedTestKeys = {
  "split", "model", "finishedAt", "correct", "scored", "unavailable", "score", "complete",
  "mode", "avgSeconds", "avgToolCalls", "promptTokens", "completionTokens", "jevFallbacks", "jevPromptTokens",
  "answerMatchCorrect", "answerMatchScored",
}


def snapshotOf(cases, world):
  gold.saveSnapshot({case["id"]: gold.resultHash(gold.runGold(world, case)) for case in cases})


def testHiddenSplitWithFailuresLeaksNothing(world, capsys, monkeypatch):
  import json

  snapshotOf(hiddenCases, world)
  replies = {
    "秘密問題甲？": "SELECT name FROM employees",
    "秘密問題乙？": "SELECT set_config('role', 'x', false)",
    "秘密問題丙？": "SELECT nope FROM employees",
    "秘密問題丁？": "UNAVAILABLE",
    "秘密問題戊？": "SELECT name FROM employees WHERE name = '劉怡君'",
  }

  def llm(model, messages):
    reply = replies[messages[-1]["content"]] if "PostgreSQL" in messages[0]["content"] else ""
    if reply == "UNAVAILABLE":
      raise LlmUnavailableError("連不上 secret-host")
    return reply

  lines = []
  realAsk = run.service.ask

  def exploding(conn, actor, question, *args, **kwargs):
    if question == "秘密問題戊？":
      raise KeyError("secret-key-text")
    return realAsk(conn, actor, question, *args, **kwargs)

  monkeypatch.setattr(run.service, "ask", exploding)
  summary = run.runSplit("test", "qwen2.5:3b", llm=llm, out=lines.append, world=world, casesOverride=hiddenCases)
  captured = capsys.readouterr()
  text = "\n".join(lines) + captured.out + captured.err
  for needle in ("h0", "秘密", "SELECT", "nope", "secret", "KeyError", "set_config"):
    assert needle not in text
  assert summary["unavailable"] == 1 and summary["scored"] == 4 and summary["correct"] == 0
  saved = json.loads(next(run.resultsDir.glob("test-*.json")).read_text(encoding="utf-8"))
  assert set(saved) == allowedTestKeys and saved["complete"] is True


def testNonAppErrorBecomesErrorOutcome(world, monkeypatch):
  def boom(*args, **kwargs):
    raise KeyError("oops")

  monkeypatch.setattr(run.service, "ask", boom)
  result = run.evaluateCase(world, miniCases[0], "qwen2.5:3b", run.makeCountingLlm(lambda m, x: ""))
  assert result["outcome"] == "error" and result["errorType"] == "KeyError"


def testUnexpectedAppErrorCodeIsError(world, monkeypatch):
  from app.infra.errors import AppError

  def boom(*args, **kwargs):
    raise AppError("QA_UNKNOWN_MODEL", "沒有這個模型", 422)

  monkeypatch.setattr(run.service, "ask", boom)
  assert run.evaluateCase(world, miniCases[0], "qwen2.5:3b", run.makeCountingLlm(lambda m, x: ""))["outcome"] == "error"


def testRunContinuesAfterErrorAndCountsAsWrong(world, monkeypatch):
  snapshotOf(miniCases, world)
  realAsk = run.service.ask

  def flaky(conn, actor, question, *args, **kwargs):
    if "工程部" in question:
      raise KeyError("oops")
    return realAsk(conn, actor, question, *args, **kwargs)

  monkeypatch.setattr(run.service, "ask", flaky)
  llm = replying({case["question"]: case["goldSql"] for case in miniCases})
  summary = run.runSplit("dev", "qwen2.5:3b", llm=llm, out=lambda line: None, world=world, casesOverride=miniCases)
  assert summary["scored"] == 2 and summary["correct"] == 1


def testPartialResultsSavedOnAbort(world, monkeypatch):
  import json
  from app.infra.errors import AppError

  snapshotOf(miniCases, world)
  realAsk = run.service.ask
  calls = []

  def abortSecond(conn, actor, question, *args, **kwargs):
    calls.append(question)
    if len(calls) == 2:
      raise AppError("QA_SANDBOX_UNAVAILABLE", "連不上", 503)
    return realAsk(conn, actor, question, *args, **kwargs)

  monkeypatch.setattr(run.service, "ask", abortSecond)
  llm = replying({case["question"]: case["goldSql"] for case in miniCases})
  with pytest.raises(run.EvalAbortError):
    run.runSplit("dev", "qwen2.5:3b", llm=llm, out=lambda line: None, world=world, casesOverride=miniCases)
  saved = json.loads(next(run.resultsDir.glob("dev-*.json")).read_text(encoding="utf-8"))
  assert saved["complete"] is False and saved["scored"] == 1 and len(saved["results"]) == 1


def testPreflightListsAllBadIds(world):
  badGold = [{**miniCases[0], "id": "b1", "goldSql": "SELECT nope FROM employees"}, {**miniCases[1], "id": "b2", "goldSql": "SELECT nope FROM employees"}]
  with pytest.raises(gold.GoldSqlError) as info:
    run.runSplit("dev", "qwen2.5:3b", llm=lambda m, x: "", world=world, casesOverride=badGold)
  assert info.value.caseIds == ["b1", "b2"]
  gold.saveSnapshot({"t01": "0" * 64, "t02": "0" * 64})
  with pytest.raises(gold.SnapshotMismatchError) as snapInfo:
    run.runSplit("dev", "qwen2.5:3b", llm=lambda m, x: "", world=world, casesOverride=miniCases)
  assert snapInfo.value.caseIds == ["t01", "t02"]


def testFilterSelection():
  assert [case["id"] for case in run.selectCases(miniCases, "leave")] == ["t02"]
  assert [case["id"] for case in run.selectCases(miniCases, "t01")] == ["t01"]


def testMainRejectsZeroMatchFilterAndSnapshotCombos():
  with pytest.raises(SystemExit) as info:
    run.main(["--split", "dev", "--filter", "no-such-category"])
  assert info.value.code == 2
  with pytest.raises(SystemExit) as info2:
    run.main(["--split", "dev", "--update-snapshot", "--filter", "org"])
  assert info2.value.code == 2


def testMainExitsOneOnGoldError(monkeypatch):
  def bad(split, model, filterText=None, **kwargs):
    raise gold.GoldSqlError(["x1", "x2"])

  monkeypatch.setattr(run, "runSplit", bad)
  with pytest.raises(SystemExit) as info:
    run.main(["--split", "dev"])
  assert info.value.code == 1


def testHeldoutLoadFailureIsGeneric(monkeypatch, capsys):
  import builtins

  realImport = builtins.__import__

  def failing(name, *args, **kwargs):
    if name == "evals.heldout_cases":
      raise NameError("secret heldout line")
    return realImport(name, *args, **kwargs)

  monkeypatch.setattr(builtins, "__import__", failing)
  with pytest.raises(SystemExit) as info:
    run.main(["--split", "test"])
  assert info.value.code == 1
  captured = capsys.readouterr()
  assert "secret" not in captured.out + captured.err and "NameError" not in captured.out + captured.err
  assert "載入失敗" in captured.err


def testSaveFailureDoesNotMaskAbort(world, monkeypatch, capsys):
  from app.infra.errors import AppError

  snapshotOf(miniCases, world)

  def abort(*args, **kwargs):
    raise AppError("QA_SANDBOX_UNAVAILABLE", "連不上", 503)

  def cannotSave(*args, **kwargs):
    raise OSError("disk full")

  monkeypatch.setattr(run.service, "ask", abort)
  monkeypatch.setattr(run, "saveResults", cannotSave)
  with pytest.raises(run.EvalAbortError):
    run.runSplit("dev", "qwen2.5:3b", llm=lambda m, x: "", out=lambda line: None, world=world, casesOverride=miniCases)
  assert "無法儲存" in capsys.readouterr().err


def toolReplies(*replies):
  queue = list(replies)

  def fake(model, messages, tools):
    return queue.pop(0) if len(queue) > 1 else queue[0]

  return fake


def sqlTool(sql):
  return ToolReply("", [ToolCall("c1", "run_sql", {"sql": sql}, "")], 50, 5)


def evaluateAgent(world, toolLlm, case=miniCases[0]):
  return run.evaluateCase(world, case, "qwen2.5:3b", run.makeCountingLlm(lambda model, messages: ""), mode="agent",
                          toolLlm=run.makeCountingToolLlm(toolLlm))


def testAgentCorrectViaTool(world):
  result = evaluateAgent(world, toolReplies(sqlTool(miniCases[0]["goldSql"]), ToolReply("好。", [], 10, 1)))
  assert result["outcome"] == "correct" and result["toolCalls"] == 1 and result["tools"] == ["run_sql"]
  assert result["mode"] == "agent" and result["noTool"] is False
  assert (result["promptTokens"], result["completionTokens"]) == (60, 6)


def testNoToolIsWrongWithFlag(world):
  result = evaluateAgent(world, toolReplies(ToolReply('<tool_call>{"name": "run_sql"}</tool_call>', [], None, None)))
  assert result["outcome"] == "wrong" and result["noTool"] is True and result["toolCalls"] == 0


def testStepsExhausted(world):
  result = evaluateAgent(world, toolReplies(sqlTool("SELECT nope FROM employees")))
  assert result["outcome"] == "stepsExhausted" and result["toolCalls"] == 4


def testAgentToolFailureIsSqlFailed(world):
  result = evaluateAgent(world, toolReplies(sqlTool("SELECT nope FROM employees"), ToolReply("算了", [], None, None)))
  assert result["outcome"] == "sqlFailed"


def testAgentResultFileNameHasMode(world):
  snapshotOf(miniCases[:1], world)
  toolLlm = toolReplies(sqlTool(miniCases[0]["goldSql"]), ToolReply("好。", [], 10, 1))
  lines = []
  summary = run.runSplit("dev", "qwen2.5:3b", out=lines.append, world=world, casesOverride=miniCases[:1], mode="agent", toolLlm=toolLlm)
  assert summary["mode"] == "agent" and summary["correct"] == 1 and summary["avgToolCalls"] == 1
  assert summary["promptTokens"] == 60 and summary["avgSeconds"] is not None
  assert [path.name.startswith("dev-agent-") for path in run.resultsDir.glob("*.json")] == [True]
  assert any("run_sql" in line for line in lines)


def testPipelineFileNameHasMode(world):
  snapshotOf(miniCases, world)
  llm = replying({case["question"]: case["goldSql"] for case in miniCases})
  summary = run.runSplit("dev", "qwen2.5:3b", llm=llm, world=world, casesOverride=miniCases, out=lambda line: None)
  assert summary["mode"] == "pipeline" and summary["avgToolCalls"] is None
  assert [path.name.startswith("dev-pipeline-") for path in run.resultsDir.glob("*.json")] == [True]


def testHiddenSplitAgentStillHidesDetails(world):
  import json

  snapshotOf(hiddenCases[:2], world)
  toolLlm = toolReplies(sqlTool("SELECT name FROM employees"), ToolReply("好。", [], 10, 1))
  lines = []
  run.runSplit("test", "qwen2.5:3b", out=lines.append, world=world, casesOverride=hiddenCases[:2], mode="agent", toolLlm=toolLlm)
  saved = json.loads(next(run.resultsDir.glob("test-*.json")).read_text(encoding="utf-8"))
  assert set(saved) == allowedTestKeys
  assert not any("run_sql" in line or "h0" in line for line in lines)


def testModeFlagChoices():
  with pytest.raises(SystemExit):
    run.main(["--split", "dev", "--mode", "x"])


def jevChooser(tool="run_sql", reason=None):
  return lambda question, now: JevDecision(tool, 0.92 if tool else 0.3, reason, 439, 0.2)


@pytest.fixture
def jevOn(monkeypatch):
  monkeypatch.setattr(jev, "isConfigured", lambda: True)


def evaluateJev(world, toolLlm, chooser, case=miniCases[0]):
  return run.evaluateCase(world, case, "qwen2.5:3b", run.makeCountingLlm(lambda model, messages: ""), mode="jev",
                          toolLlm=run.makeCountingToolLlm(toolLlm), chooseTool=chooser)


def testJevModeRecordsRoute(world, jevOn):
  result = evaluateJev(world, toolReplies(sqlTool(miniCases[0]["goldSql"]), ToolReply("好。", [], 10, 1)), jevChooser())
  assert result["outcome"] == "correct" and result["mode"] == "jev" and result["toolCalls"] == 1
  assert (result["routeTool"], result["routeConfidence"], result["routeFallback"]) == ("run_sql", 0.92, None)
  assert (result["jevPromptTokens"], result["jevSeconds"]) == (439, 0.2)


def testJevRouteRecordedWhenQueryFails(world, jevOn):
  result = evaluateJev(world, toolReplies(sqlTool("SELECT nope FROM employees"), ToolReply("算了", [], None, None)),
                       jevChooser(None, "low_confidence"))
  assert result["outcome"] == "sqlFailed" and result["routeFallback"] == "low_confidence" and result["routeTool"] is None


def testJevSummary():
  base = {"category": "org", "seconds": 1.0, "toolCalls": 1, "promptTokens": 10, "completionTokens": 1}
  results = [
    {**base, "outcome": "correct", "routeTool": "find_available_people", "routeFallback": None, "jevPromptTokens": 400},
    {**base, "outcome": "wrong", "routeTool": "find_available_people", "routeFallback": None, "jevPromptTokens": 420},
    {**base, "outcome": "correct", "routeTool": None, "routeFallback": "low_confidence", "jevPromptTokens": 430},
    {**base, "outcome": "unavailable", "routeTool": None, "routeFallback": None, "jevPromptTokens": None},
  ]
  summary = run.summarize("dev", "qwen2.5:3b", results, "jev")
  assert summary["jevFallbacks"] == 1 and summary["jevPromptTokens"] == 1250
  assert summary["routeCounts"] == {"find_available_people": 2, "fallback": 1}
  assert run.summarize("dev", "qwen2.5:3b", results, "agent")["jevFallbacks"] is None


def testJevOutputLines():
  lines = []
  base = {"id": "d01", "asker": "boss", "outcome": "correct", "retried": False, "seconds": 1.0, "sql": None, "mode": "jev",
          "tools": ["find_available_people"], "toolCalls": 1}
  run.printCase(lines.append, {**base, "routeTool": "find_available_people", "routeConfidence": 0.923, "routeFallback": None})
  run.printCase(lines.append, {**base, "routeTool": None, "routeConfidence": 0.3, "routeFallback": "low_confidence"})
  assert "   Jev：find_available_people（0.92）" in lines and "   Jev：退回（low_confidence）" in lines


def testJevResultFileNameAndHiddenKeys(world, jevOn):
  import json

  snapshotOf(hiddenCases[:2], world)
  toolLlm = toolReplies(sqlTool("SELECT name FROM employees"), ToolReply("好。", [], 10, 1))
  lines = []
  run.runSplit("test", "qwen2.5:3b", out=lines.append, world=world, casesOverride=hiddenCases[:2], mode="jev",
               toolLlm=toolLlm, chooseTool=jevChooser())
  path = next(run.resultsDir.glob("test-jev-*.json"))
  saved = json.loads(path.read_text(encoding="utf-8"))
  # 各工具被選中的次數會洩漏 test 題型的分布，只留退回次數和 token 總和
  assert set(saved) == allowedTestKeys and saved["jevPromptTokens"] == 878
  assert not any("Jev" in line or "run_sql" in line for line in lines)


def testJevWithoutKeyAbortsEval(world, monkeypatch):
  monkeypatch.setattr(jev, "isConfigured", lambda: False)
  with pytest.raises(run.EvalAbortError):
    evaluateJev(world, toolReplies(ToolReply("x", [], None, None)), jevChooser())


def testModeFlagAcceptsJev(monkeypatch):
  seen = {}
  monkeypatch.setattr(run, "runSplit", lambda *args, **kwargs: seen.update(kwargs))
  monkeypatch.setattr(run.llmModule, "listModels", lambda: [{"id": "qwen2.5:3b"}])
  run.main(["--split", "dev", "--mode", "jev"])
  assert seen["mode"] == "jev"


# ---------- 最後的回答 ----------


def testAgentResultKeepsAnswer(world):
  result = evaluateAgent(world, toolReplies(sqlTool(miniCases[0]["goldSql"]), ToolReply("工程部有陳大文", [], 10, 1)))
  assert result["answer"] == "工程部有陳大文"
  assert isinstance(result["answerMatch"], bool)
  assert isinstance(result["goldAll"], list) and result["goldAll"]


def testPipelineHasNoAnswer(world):
  result = evaluate(world, miniCases[0]["goldSql"])
  assert result["answer"] is None and result["answerMatch"] is None


def testUnavailableHasNoAnswerScore(world):
  def down(model, messages, tools):
    raise LlmUnavailableError("連不上")

  result = evaluateAgent(world, down)
  assert result["outcome"] == "unavailable"
  assert result["answer"] is None and result["answerMatch"] is None


def testSummaryCountsAnswerMatch():
  base = {"category": "org", "seconds": 1.0, "outcome": "correct"}
  results = [{**base, "answerMatch": True}, {**base, "answerMatch": False}, {**base, "answerMatch": None}]
  summary = run.summarize("dev", "qwen2.5:3b", results, "agent")
  assert summary["answerMatchCorrect"] == 1 and summary["answerMatchScored"] == 2


def testHiddenSplitPrintsAnswerMatchTotal(world):
  snapshotOf(hiddenCases[:2], world)
  toolLlm = toolReplies(sqlTool("SELECT name FROM employees"), ToolReply("秘密回答丙", [], 10, 1))
  lines = []
  run.runSplit("test", "qwen2.5:3b", out=lines.append, world=world, casesOverride=hiddenCases[:2], mode="agent", toolLlm=toolLlm)
  assert any(line.startswith("回答（字串比對）：") for line in lines)
  assert not any("秘密回答丙" in line for line in lines)


def testJudgeFlagNeedsAgentMode():
  with pytest.raises(SystemExit):
    run.main(["--split", "dev", "--judge", "google/gemini-3.5-flash-lite"])


def testHiddenSplitJudgeLeaksNothing(world):
  import json

  snapshotOf(hiddenCases[:2], world)
  toolLlm = toolReplies(sqlTool("SELECT name FROM employees"), ToolReply("秘密回答丙", [], 10, 1))
  lines = []
  callJudge = lambda model, messages: '{"verdict": "wrong", "reason": "秘密理由丁"}'
  run.runSplit("test", "qwen2.5:3b", out=lines.append, world=world, casesOverride=hiddenCases[:2], mode="agent", toolLlm=toolLlm,
               judgeModel="judge-model", callJudge=callJudge)
  saved = json.loads(next(run.resultsDir.glob("test-*.json")).read_text(encoding="utf-8"))
  judgeKeys = {"judgeModel", "judgeCorrect", "judgeScored", "judgeFailed", "judgeUnavailable"}
  assert set(saved) == allowedTestKeys | judgeKeys
  assert any(line.startswith("回答（評審）：") for line in lines)
  assert not any("秘密回答丙" in line or "秘密理由丁" in line or "h0" in line for line in lines)


def testFailedAgentCaseCountsAsWrongAnswer(world):
  result = evaluateAgent(world, toolReplies(sqlTool("SELECT nope FROM employees"), ToolReply("算了", [], None, None)))
  assert result["outcome"] != "unavailable" and result["answer"] is None
  assert result["answerMatch"] is False
