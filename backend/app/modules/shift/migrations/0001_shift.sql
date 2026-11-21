CREATE TABLE shift_types (
  id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code text NOT NULL UNIQUE CHECK (code ~ '^[a-z][a-z0-9_]*$'),
  name text NOT NULL UNIQUE CHECK (btrim(name) <> ''),
  -- end_time 早於 start_time 代表跨過午夜；這種班算在開始那天
  start_time time NOT NULL,
  end_time time NOT NULL,
  break_start time NULL,
  break_end time NULL,
  is_default boolean NOT NULL DEFAULT false,
  is_active boolean NOT NULL DEFAULT true,
  CHECK (start_time <> end_time),
  CHECK ((break_start IS NULL) = (break_end IS NULL)),
  -- 請假的最小單位是 1 小時、時數存整數；半點的班會讓請假算出半小時
  CHECK (extract(minute FROM start_time) = 0 AND extract(second FROM start_time) = 0),
  CHECK (extract(minute FROM end_time) = 0 AND extract(second FROM end_time) = 0),
  CHECK (break_start IS NULL OR (extract(minute FROM break_start) = 0 AND extract(second FROM break_start) = 0)),
  CHECK (break_end IS NULL OR (extract(minute FROM break_end) = 0 AND extract(second FROM break_end) = 0)),
  -- 沒排班的人都套用預設班，停用了就等於大家都休息
  CHECK (NOT is_default OR is_active)
);

CREATE UNIQUE INDEX shift_types_one_default_idx ON shift_types (is_default) WHERE is_default;

-- 要換班表就新增一張，舊的保留，過去某天上什麼班才查得回來
CREATE TABLE shift_rosters (
  id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  employee_id int NOT NULL REFERENCES employees (id),
  effective_from date NOT NULL,
  created_by int NOT NULL REFERENCES users (id),
  created_at timestamp NOT NULL,
  UNIQUE (employee_id, effective_from)
);

-- 沒有列出的星期幾就是休息
CREATE TABLE shift_roster_days (
  roster_id int NOT NULL REFERENCES shift_rosters (id) ON DELETE CASCADE,
  weekday int NOT NULL CHECK (weekday BETWEEN 0 AND 6),
  shift_type_id int NOT NULL REFERENCES shift_types (id),
  PRIMARY KEY (roster_id, weekday)
);

CREATE TABLE shift_overrides (
  id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  employee_id int NOT NULL REFERENCES employees (id),
  day date NOT NULL,
  -- NULL 代表那天休息
  shift_type_id int NULL REFERENCES shift_types (id),
  note text NOT NULL DEFAULT '',
  created_by int NOT NULL REFERENCES users (id),
  created_at timestamp NOT NULL,
  updated_by int NOT NULL REFERENCES users (id),
  updated_at timestamp NOT NULL,
  UNIQUE (employee_id, day)
);

INSERT INTO shift_types (code, name, start_time, end_time, break_start, break_end, is_default)
VALUES ('standard', '標準班', '09:00', '18:00', '12:00', '13:00', true);
