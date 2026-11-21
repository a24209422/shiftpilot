import pytest

from app.modules.qa.llm import LlmUnavailableError
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
allowedTestKeys = {"split", "model", "finishedAt", "correct", "scored", "unavailable", "score", "complete"}


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
