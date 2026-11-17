-- 這份 schema 也會原封不動塞進 text2sql 的 prompt，所以欄位註解是寫給 LLM 看的

-- 可被排程的對象。用 type 區分種類，之後要擴充成通用排程（設備、車輛、教室…）只需新增 type，不用改表
CREATE TABLE IF NOT EXISTS resources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,          -- 名稱，例如 '王小明'、'A 會議室'
  type TEXT NOT NULL,          -- 種類：person（人）、room（會議室）、equipment（設備）
  note TEXT
);

-- 排程。一筆排程佔用一個 resource 的一段時間
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,         -- 標題，例如 '週會'、'早班'
  category TEXT NOT NULL,      -- 分類：meeting（會議）、shift（班別）、task（工作）、booking（借用）
  start_at TEXT NOT NULL,      -- 開始時間，格式 'YYYY-MM-DD HH:MM'
  end_at TEXT NOT NULL,        -- 結束時間，格式 'YYYY-MM-DD HH:MM'
  resource_id INTEGER NOT NULL REFERENCES resources(id),
  note TEXT,
  CHECK (end_at > start_at)
);

CREATE INDEX IF NOT EXISTS idx_events_resource_time ON events (resource_id, start_at);
