-- 排程明細。一列 = 一筆排程 × 一個參與的資源。
-- 一筆排程有幾個資源就有幾列，這些列的 event_id 相同（例如 2 個人加 1 間會議室的會議有 3 列）。
CREATE TABLE event_details (
  event_id INTEGER,      -- 排程編號。同一筆排程的每一列都相同
  title TEXT,            -- 排程標題，例如 '週會'、'早班'
  category TEXT,         -- 分類：meeting（會議）、shift（班別）、task（工作）、booking（借用）
  start_at TIMESTAMP,    -- 開始時間，例如 '2026-11-17 10:00'
  end_at TIMESTAMP,      -- 結束時間，例如 '2026-11-17 11:00'
  resource_name TEXT,    -- 參與這筆排程的資源名稱，例如 '王小明'、'A 會議室'
  resource_type TEXT     -- 資源種類：person（人）、room（會議室）、equipment（設備）
);

-- 所有可被排程的對象，包含目前沒有任何排程的。
CREATE TABLE resources (
  id INTEGER,
  name TEXT,             -- 名稱，例如 '王小明'、'A 會議室'
  type TEXT              -- 種類：person（人）、room（會議室）、equipment（設備）
);
