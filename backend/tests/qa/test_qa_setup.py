import psycopg

from app.config import buildQaDatabaseUrl, loadConfig


def testBuildQaDatabaseUrlKeepsHostAndDatabase():
  url = buildQaDatabaseUrl("postgresql://schedule_app:secret@postgres:5432/schedule", "abc123")
  assert url == "postgresql://qa_sandbox:abc123@postgres:5432/schedule"


def testLoadConfigBuildsQaUrlOnlyWhenPasswordSet(monkeypatch):
  monkeypatch.setenv("DATABASE_URL", "postgresql://schedule_app:secret@127.0.0.1:5433/schedule")
  monkeypatch.setenv("QA_DB_PASSWORD", "abc123")
  assert loadConfig().qaDatabaseUrl == "postgresql://qa_sandbox:abc123@127.0.0.1:5433/schedule"
  monkeypatch.setenv("QA_DB_PASSWORD", "")
  assert loadConfig().qaDatabaseUrl is None


def testSandboxAccountHasNoPrivilegesOrMemberships(qaSandboxUrl):
  with psycopg.connect(qaSandboxUrl) as conn:
    role = conn.execute(
      "SELECT rolsuper, rolcreaterole, rolcreatedb, rolinherit, rolbypassrls FROM pg_roles WHERE rolname = current_user"
    ).fetchone()
    memberships = conn.execute(
      "SELECT count(*) FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.member WHERE r.rolname = current_user"
    ).fetchone()[0]
    sessionUser = conn.execute("SELECT session_user").fetchone()[0]
  assert role == (False, False, False, False, False)
  assert memberships == 0
  assert sessionUser == "qa_sandbox"


def testQaModuleIsListedForEmployees(client, loginAs):
  loginAs("employee", employee=True)
  modules = {item["name"]: item["permissions"] for item in client.get("/api/modules").json()}
  assert modules["qa"] == ["qa.ask"]
