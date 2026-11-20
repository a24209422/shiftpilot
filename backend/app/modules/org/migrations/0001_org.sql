CREATE TABLE departments (
  id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name text NOT NULL UNIQUE,
  parent_id int NULL REFERENCES departments (id),
  CHECK (parent_id IS NULL OR parent_id <> id)
);

CREATE TABLE employees (
  id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  employee_no text NOT NULL UNIQUE,
  name text NOT NULL,
  email text NULL,
  department_id int NOT NULL REFERENCES departments (id),
  job_title text NOT NULL,
  manager_id int NULL REFERENCES employees (id),
  hired_on date NOT NULL,
  is_active boolean NOT NULL DEFAULT true,
  left_on date NULL,
  CHECK (manager_id IS NULL OR manager_id <> id),
  CHECK (left_on IS NULL OR left_on >= hired_on)
);

CREATE INDEX employees_department_id_idx ON employees (department_id);
CREATE INDEX employees_manager_id_idx ON employees (manager_id);

-- 台灣有補班日，所以不是只有假日一種
CREATE TABLE calendar_days (
  day date PRIMARY KEY,
  kind text NOT NULL CHECK (kind IN ('holiday', 'makeup_workday')),
  name text NOT NULL
);
