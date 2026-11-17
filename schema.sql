-- 實際建表用的結構。給 text2sql 模型看的說明在 llm_schema.sql，兩邊的欄位要保持一致

-- 可被排程的對象。用 type 區分種類，之後要擴充成通用排程（設備、車輛、教室…）只需新增 type，不用改表
CREATE TABLE IF NOT EXISTS resources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  type TEXT NOT NULL,
  note TEXT
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  category TEXT NOT NULL,
  start_at TEXT NOT NULL,      -- 'YYYY-MM-DD HH:MM'，固定長度所以可以直接用字串比較先後
  end_at TEXT NOT NULL,
  note TEXT,
  CHECK (end_at > start_at)
);

-- 一筆排程可以有多個資源（多個人加一間會議室），一個資源也會出現在多筆排程
CREATE TABLE IF NOT EXISTS event_resources (
  event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  resource_id INTEGER NOT NULL REFERENCES resources(id),
  PRIMARY KEY (event_id, resource_id)
);

CREATE INDEX IF NOT EXISTS idx_events_start ON events (start_at);
CREATE INDEX IF NOT EXISTS idx_event_resources_resource ON event_resources (resource_id);

-- 攤平成「一筆排程 × 一個資源」一列，text2sql 只查這張 view：小模型不用自己寫兩次 JOIN
CREATE VIEW IF NOT EXISTS event_details AS
SELECT
  e.id AS event_id,
  e.title,
  e.category,
  e.start_at,
  e.end_at,
  r.name AS resource_name,
  r.type AS resource_type
FROM events e
JOIN event_resources er ON er.event_id = e.id
JOIN resources r ON r.id = er.resource_id;
