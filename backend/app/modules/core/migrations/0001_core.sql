CREATE TABLE users (
  id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  email text NOT NULL,
  password_hash text NOT NULL,
  role text NOT NULL CHECK (role IN ('employee', 'manager', 'hr', 'admin')),
  -- 管理員帳號不一定是員工，所以可為空
  employee_id int NULL UNIQUE REFERENCES employees (id),
  is_active boolean NOT NULL DEFAULT true,
  last_login_at timestamp NULL,
  failed_login_count int NOT NULL DEFAULT 0,
  locked_until timestamp NULL,
  created_at timestamp NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX users_email_lower_idx ON users (lower(email));

-- 只存 token 的雜湊：資料庫外洩時，拿到的 session 不能直接拿去登入
CREATE TABLE sessions (
  id_hash text PRIMARY KEY,
  user_id int NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  expires_at timestamp NOT NULL,
  created_at timestamp NOT NULL DEFAULT now()
);

CREATE INDEX sessions_user_id_idx ON sessions (user_id);

CREATE TABLE audit_log (
  id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  at timestamp NOT NULL DEFAULT now(),
  user_id int NULL REFERENCES users (id),
  module text NOT NULL,
  action text NOT NULL,
  entity text NOT NULL,
  entity_id text NOT NULL,
  before jsonb NULL,
  after jsonb NULL
);

CREATE INDEX audit_log_module_idx ON audit_log (module, id DESC);

-- 稽核紀錄只能新增：連應用程式自己的帳號也不能改或刪
DO $$
BEGIN
  EXECUTE format('REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM %I', current_user);
END
$$;
