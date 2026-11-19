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

-- 部門，可以有上層部門（例如總經理室底下有業務部、營運部）。
CREATE TABLE departments (
  id INTEGER,
  name TEXT,             -- 部門名稱，例如 '營運部'
  parent_id INTEGER      -- 上層部門的 departments.id；最上層的部門是 NULL
);

-- 員工。每個員工對應 resources 裡一個 type = 'person' 的資源，姓名在 resources.name。
CREATE TABLE employees (
  id INTEGER,
  resource_id INTEGER,   -- 對應 resources.id（那一筆的 type 是 person）
  department_id INTEGER, -- 對應 departments.id
  job_title TEXT,        -- 職稱，例如 '營運組長'
  manager_id INTEGER,    -- 主管的 employees.id；最上層的人是 NULL
  hired_on DATE          -- 到職日
);

-- 會議室的細節。每間對應 resources 裡一個 type = 'room' 的資源，名稱在 resources.name。
CREATE TABLE rooms (
  resource_id INTEGER,           -- 對應 resources.id（那一筆的 type 是 room）
  floor SMALLINT,                -- 樓層
  capacity SMALLINT,             -- 容納人數
  has_video_conference BOOLEAN   -- 有沒有視訊設備
);

-- 固定班表員工的每週上班時段。輪班的員工沒有這裡的資料，上班時間看 events 裡 category = 'shift' 的排程。
CREATE TABLE work_hours (
  employee_id INTEGER,   -- 對應 employees.id
  weekday SMALLINT,      -- 星期幾：1 = 星期一 … 7 = 星期日，與 EXTRACT(ISODOW FROM ...) 相同
  start_time TIME,       -- 上班時間，例如 '09:00'
  end_time TIME          -- 下班時間，例如 '18:00'
);

-- 請假，可以跨好幾天。只有 status = 'approved' 的才算真的請假。
CREATE TABLE leave_requests (
  id INTEGER,
  employee_id INTEGER,   -- 對應 employees.id
  leave_type TEXT,       -- 假別：annual（特休）、sick（病假）、personal（事假）
  start_at TIMESTAMP,    -- 請假開始時間
  end_at TIMESTAMP,      -- 請假結束時間
  status TEXT            -- 審核狀態：pending（審核中）、approved（核准）、rejected（駁回）
);

-- 不用上班的日子：國定假日與公司特別休假日。
CREATE TABLE holidays (
  day DATE,              -- 日期
  name TEXT              -- 名稱，例如 '行憲紀念日'
);
