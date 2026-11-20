import psycopg
import pytest

from app.infra.db import openDb
from app.infra.migrate import runMigrations
from app.infra.registry import ModuleManifest


def makeModule(root, name, files, dependsOn=()):
  directory = root / name
  directory.mkdir()
  for fileName, text in files.items():
    (directory / fileName).write_text(text, encoding="utf-8")
  return ModuleManifest(name, name, tuple(dependsOn), (), directory)


def tableNames(url):
  with openDb(url) as conn:
    rows = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()").fetchall()
  return {row["table_name"] for row in rows}


def testRunMigrationsAppliesInOrderAndRecords(databaseUrl, tmp_path):
  first = makeModule(tmp_path, "first", {"0001_a.sql": "CREATE TABLE a (id int);"})
  second = makeModule(tmp_path, "second", {"0001_b.sql": "CREATE TABLE b (a_id int);"}, ["first"])
  applied = runMigrations(databaseUrl, [second, first])
  assert applied == ["first/0001_a.sql", "second/0001_b.sql"]
  assert {"a", "b"} <= tableNames(databaseUrl)
  with openDb(databaseUrl) as conn:
    assert conn.execute("SELECT count(*) AS n FROM schema_migrations").fetchone()["n"] == 2


def testRunMigrationsAppliesFilesInNameOrderWithinModule(databaseUrl, tmp_path):
  module = makeModule(tmp_path, "m", {"0002_b.sql": "ALTER TABLE a ADD COLUMN extra int;", "0001_a.sql": "CREATE TABLE a (id int);"})
  assert runMigrations(databaseUrl, [module]) == ["m/0001_a.sql", "m/0002_b.sql"]


def testRunMigrationsIsIdempotent(databaseUrl, tmp_path):
  module = makeModule(tmp_path, "first", {"0001_a.sql": "CREATE TABLE a (id int);"})
  assert runMigrations(databaseUrl, [module]) == ["first/0001_a.sql"]
  assert runMigrations(databaseUrl, [module]) == []


def testFailedMigrationRollsBackAndIsNotRecorded(databaseUrl, tmp_path):
  module = makeModule(tmp_path, "bad", {"0001_bad.sql": "CREATE TABLE half (id int);\nSELEKT broken;"})
  with pytest.raises(psycopg.errors.SyntaxError):
    runMigrations(databaseUrl, [module])
  assert "half" not in tableNames(databaseUrl)
  with openDb(databaseUrl) as conn:
    assert conn.execute("SELECT count(*) AS n FROM schema_migrations").fetchone()["n"] == 0
