CREATE TABLE leave_types (
  id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code text NOT NULL UNIQUE CHECK (code ~ '^[a-z][a-z0-9_]*$'),
  name text NOT NULL UNIQUE CHECK (btrim(name) <> ''),
  -- 給之後的薪資模組參考，請假模組本身不使用
  paid_ratio numeric(3, 2) NOT NULL CHECK (paid_ratio BETWEEN 0 AND 1),
  quota_kind text NOT NULL CHECK (quota_kind IN ('seniority', 'yearly_cap', 'none')),
  annual_cap_hours int NULL CHECK (annual_cap_hours > 0),
  is_active boolean NOT NULL DEFAULT true,
  CHECK ((quota_kind = 'yearly_cap') = (annual_cap_hours IS NOT NULL))
);

-- 特休的額度由年資規則算，只能有一種
CREATE UNIQUE INDEX leave_types_one_seniority_idx ON leave_types (quota_kind) WHERE quota_kind = 'seniority';

CREATE TABLE leave_requests (
  id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  employee_id int NOT NULL REFERENCES employees (id),
  leave_type_id int NOT NULL REFERENCES leave_types (id),
  start_at timestamp NOT NULL,
  end_at timestamp NOT NULL,
  -- 送出時算好的快照：之後人資改了假日，已核准的時數不會跟著悄悄改變
  hours int NOT NULL CHECK (hours > 0),
  reason text NOT NULL DEFAULT '',
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'withdrawn', 'cancelled')),
  decided_by int NULL REFERENCES users (id),
  decided_at timestamp NULL,
  decision_note text NULL,
  cancelled_by int NULL REFERENCES users (id),
  cancelled_at timestamp NULL,
  created_by int NOT NULL REFERENCES users (id),
  created_at timestamp NOT NULL,
  CHECK (end_at > start_at),
  -- cancelled 只會從 approved 來，所以也有核准紀錄
  CHECK ((status IN ('approved', 'rejected', 'cancelled')) = (decided_at IS NOT NULL)),
  CHECK ((decided_at IS NULL) = (decided_by IS NULL)),
  CHECK ((status IN ('withdrawn', 'cancelled')) = (cancelled_at IS NOT NULL)),
  CHECK ((cancelled_at IS NULL) = (cancelled_by IS NULL)),
  -- 同一個人還有效的申請不能重疊；由資料庫保證，兩張同時送出也一樣
  EXCLUDE USING gist (employee_id WITH =, tsrange(start_at, end_at) WITH &&) WHERE (status IN ('pending', 'approved'))
);

CREATE INDEX leave_requests_employee_start_idx ON leave_requests (employee_id, start_at);
CREATE INDEX leave_requests_status_idx ON leave_requests (status);

-- 只能新增：要更正就再加一筆反向的，稽核才看得出來改過什麼
CREATE TABLE leave_adjustments (
  id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  employee_id int NOT NULL REFERENCES employees (id),
  leave_type_id int NOT NULL REFERENCES leave_types (id),
  period_start date NOT NULL,
  hours int NOT NULL CHECK (hours <> 0),
  reason text NOT NULL CHECK (btrim(reason) <> ''),
  created_by int NOT NULL REFERENCES users (id),
  created_at timestamp NOT NULL
);

CREATE INDEX leave_adjustments_lookup_idx ON leave_adjustments (employee_id, leave_type_id, period_start);

-- 參考資料，不是示範資料：台灣常用的法定假別。小時數 = 天數 × 8
INSERT INTO leave_types (code, name, paid_ratio, quota_kind, annual_cap_hours) VALUES
  ('annual', '特休', 1, 'seniority', NULL),
  ('personal', '事假', 0, 'yearly_cap', 112),
  ('sick', '病假', 0.5, 'yearly_cap', 240),
  ('menstrual', '生理假', 0.5, 'yearly_cap', 24),
  ('marriage', '婚假', 1, 'yearly_cap', 64),
  ('paternity', '陪產檢及陪產假', 1, 'yearly_cap', 56),
  ('bereavement', '喪假', 1, 'none', NULL),
  ('official', '公假', 1, 'none', NULL),
  ('maternity', '產假', 1, 'none', NULL);
