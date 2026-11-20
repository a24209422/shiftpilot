import psycopg
from psycopg.rows import dict_row

from app.infra.db import ensureExtensions
from app.infra.registry import ModuleManifest, orderModules


def runMigrations(databaseUrl: str, manifests: list[ModuleManifest]) -> list[str]:
  ensureExtensions(databaseUrl)
  applied: list[str] = []
  # autocommit 加上 transaction()：每個遷移檔自己是一個交易，失敗只回復那一檔
  with psycopg.connect(databaseUrl, autocommit=True, row_factory=dict_row) as conn:
    conn.execute(
      "CREATE TABLE IF NOT EXISTS schema_migrations ("
      "module text NOT NULL, version text NOT NULL, applied_at timestamp NOT NULL DEFAULT now(), "
      "PRIMARY KEY (module, version))"
    )
    done = {(row["module"], row["version"]) for row in conn.execute("SELECT module, version FROM schema_migrations").fetchall()}
    for manifest in orderModules(manifests):
      for path in sorted(manifest.migrationsDir.glob("*.sql"), key=lambda item: item.name):
        if (manifest.name, path.name) in done:
          continue
        with conn.transaction():
          conn.execute(path.read_text(encoding="utf-8"))
          conn.execute("INSERT INTO schema_migrations (module, version) VALUES (%s, %s)", (manifest.name, path.name))
        applied.append(f"{manifest.name}/{path.name}")
  return applied
