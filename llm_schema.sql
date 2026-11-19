-- 排程。一筆排程一列。排程用到哪些資源，記在 event_resources。
CREATE TABLE events (
  id INTEGER,            -- 排程編號
  title TEXT,            -- 排程標題，例如 '週會'、'早班'
  category TEXT,         -- 分類：meeting（會議）、shift（班別）、task（工作）、booking（借用）
  start_at TIMESTAMP,    -- 開始時間，例如 '2026-11-17 10:00'
  end_at TIMESTAMP,      -- 結束時間，例如 '2026-11-17 11:00'
  note TEXT              -- 備註，可能是 NULL
);

-- 排程和資源的對應。一筆排程可以有多個資源（例如 2 個人加 1 間會議室），
-- 有幾個資源就有幾列，這些列的 event_id 相同。
CREATE TABLE event_resources (
  event_id INTEGER,      -- 對應 events.id
  resource_id INTEGER,   -- 對應 resources.id
  position SMALLINT      -- 新增排程時選資源的順序，查詢時通常用不到
);

-- 所有可被排程的對象，包含目前沒有任何排程的。
CREATE TABLE resources (
  id INTEGER,
  name TEXT,             -- 名稱，例如 '王小明'、'A 會議室'
  type TEXT,             -- 種類：person（人）、room（會議室）、equipment（設備）
  note TEXT              -- 備註，可能是 NULL
);
