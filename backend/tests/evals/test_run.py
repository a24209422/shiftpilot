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


def testUnavailableIsNotScored(world, capsys):
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
  assert info.value.caseIds == ["t01"]


def testUpdateSnapshot(world):
  assert run.updateSnapshot("dev", world=world, casesOverride=miniCases) == ["t01", "t02"]
  assert set(gold.loadSnapshot()) == {"t01", "t02"}


def testFilterOnlyForDev(world):
  with pytest.raises(SystemExit):
    run.main(["--split", "test", "--filter", "org"])


def testUnknownModelIsRejected():
  with pytest.raises(SystemExit):
    run.main(["--split", "dev", "--model", "gpt-x"])


def testSandboxUnavailableAbortsInsteadOfScoring(world, monkeypatch):
  from app.infra.errors import AppError

  def broken(*args, **kwargs):
    raise AppError("QA_SANDBOX_UNAVAILABLE", "問答沙盒帳號連不上", 503)

  monkeypatch.setattr(run.service, "ask", broken)
  with pytest.raises(run.EvalAbortError):
    evaluate(world, "SELECT 1")
