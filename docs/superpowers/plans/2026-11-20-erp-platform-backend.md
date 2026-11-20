# 請假排班系統：後端（階段 0、1）實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立模組化的 FastAPI 後端：組織、資源預約、登入與角色、稽核。資料結構從零設計，由資料庫保證同一資源不會重複預約。

**Architecture:** 後端是 Python 套件 `backend/app`：`infra/` 放共用的連線、遷移、模組登記、權限、HTTP 基礎；`modules/{org,core,booking}/` 各自帶遷移、service、router。service 的第一個參數是資料庫連線，一個 HTTP 請求一個交易；router 只做權限檢查與格式轉換。

**Tech Stack:** Python 3.13、FastAPI、psycopg 3、PostgreSQL 17（`btree_gist` 擴充）、argon2-cffi、pytest（真的資料庫，每個測試一個暫時 schema）。

**Spec:** `docs/superpowers/specs/2026-11-20-erp-platform-design.md`

**範圍：** 只做設計文件的階段 0、1（後端）。階段 2（前端）、階段 3（切換、更新 README、移除舊的 app 容器）等後端完成後另寫計畫，才能對著真的 API 寫。

**開始前（準備）：** ① 啟動 Docker Desktop，執行 `docker compose up -d --wait postgres`（Docker 現在沒有在跑）。② 從 `main` 建立分支 `platform-backend`，所有 commit 都在這個分支。③ 目前 `docs/superpowers/specs/2026-11-20-erp-platform-design.md` 與 `prototype/` 未進 git；設計文件在任務 1 一起 commit，`prototype/` 留給前端計畫處理。

## Global Constraints

- 縮排 2 個空白、camelCase 命名、註解用正體中文且只說「為什麼」。Python 也照這個，不改成 snake_case；資料庫欄位用 snake_case。
- PostgreSQL 17、Python 3.13；需要 `btree_gist` 擴充。時間欄位都是 `timestamp`（不帶時區，單一時區）。
- API 的 JSON 欄位用 camelCase；時間格式 `YYYY-MM-DDTHH:MM:SS`，不接受含時區位移的輸入。
- 錯誤格式一律 `{ "error": { "code", "message", "details" } }`。
- 角色只有 `employee`、`manager`、`hr`、`admin`；角色對應哪些權限寫在程式裡，不放資料庫。
- 密碼只放 `.env`、不寫進程式碼；雜湊用 `argon2id`；session 存資料庫，cookie 設 `HttpOnly`、`SameSite=Lax`；非 GET 請求要帶自訂標頭才放行（擋 CSRF）。
- 只綁 `127.0.0.1`。
- 排程可以跨日；取消是狀態（`cancelled`），不提供刪除；資源與員工不真的刪除，改成停用。
- 舊程式搬到 `legacy/`，不刪、不維護、不在測試中執行；不寫「舊資料搬新資料」的程式。
- 沒有 Ollama 與雲端模型的設定；問答（text2sql）不在這份計畫內。

## Review Focus

設計文件沒說、但最可能讓使用者踩到的輸入，每一項在負責的任務裡有對應的測試：

1. 同一個資源或同一位員工在同一筆預約裡重複出現 → 去重，不報資料庫錯誤（任務 10）
2. 已停用的資源或員工被排進預約 → 拒絕，`INACTIVE_REFERENCE`（任務 10）
3. 沒有員工身分的帳號（管理員）建立預約 → 要求指定主辦人，`ORGANIZER_REQUIRED`（任務 10）
4. 登入時 email 大小寫不同、前後有空白 → 照樣登入成功（任務 8）
5. 已停用的帳號、已過期的 session 仍拿著 cookie → 一律當作未登入（任務 8）

## 檔案結構

```
legacy/                     搬移，內容不改：app.py db.py text2sql.py schema.sql llm_schema.sql evals/ tests/ pytest.ini Dockerfile .env.example
backend/
  requirements.txt  pytest.ini
  app/
    config.py                 loadConfig()
    main.py                   createApp(databaseUrl)、createAppFromEnv()
    cli.py                    migrate / createUser / seedDemo
    infra/
      db.py                   openDb、temporarySchema、ensureExtensions
      errors.py  serialize.py  actor.py
      registry.py             ModuleManifest、模組排序、「不可用」提供者登記
      migrate.py              runMigrations
      permissions.py          rolePermissions、hasPermission
      http.py                 連線、登入身分、權限、CSRF、錯誤處理
    modules/
      __init__.py             allModules
      org/     manifest.py  migrations/0001_org.sql     service.py  router.py
      core/    manifest.py  migrations/0001_core.sql    security.py service.py router.py
      booking/ manifest.py  migrations/0001_booking.sql service.py  router.py
  tests/  conftest.py  infra/  org/  core/  booking/  test_cli.py
```

遷移順序依模組的 `dependsOn`：`org` → `core`（`users.employee_id` 指向 `employees`）→ `booking`。

## API 清單

階段 2 的前端要對每個寫入動作做出入口；下表就是核對清單。所有非 GET 請求都要帶標頭 `X-App-Client: web`。

| 方法與路徑 | 權限 | 說明 |
|---|---|---|
| `POST /api/auth/login`、`POST /api/auth/logout`、`GET /api/auth/me`、`POST /api/auth/password` | 登入者（login 例外） | 登入、登出、目前使用者、改自己的密碼 |
| `GET /api/modules` | 登入者 | 目前使用者看得到的模組 |
| `GET/POST /api/core/users`、`PATCH /api/core/users/{id}`、`POST /api/core/users/{id}/password`、`GET /api/core/audit` | `core.users.manage`、`core.audit.read` | 帳號管理、重設密碼、稽核紀錄 |
| `GET/POST /api/org/departments`、`PATCH /api/org/departments/{id}` | 讀 `org.read`／寫 `org.manage` | 部門 |
| `GET/POST /api/org/employees`、`PATCH /api/org/employees/{id}` | 同上 | 員工（含停用、離職日） |
| `GET /api/org/calendarDays`、`PUT/DELETE /api/org/calendarDays/{day}` | 同上 | 行事曆（假日、補班日） |
| `GET/POST /api/booking/resources`、`PATCH /api/booking/resources/{id}` | 讀 `booking.read`／寫 `booking.resources.manage` | 資源 |
| `GET/POST /api/booking/bookings`、`PATCH /api/booking/bookings/{id}`、`POST /api/booking/bookings/{id}/cancel` | `booking.read`／`booking.write`（改與取消另外檢查「自己建立的」或 `booking.writeAny`） | 排程 |
| `GET /api/booking/summary` | `booking.read` | 首頁小工具用的摘要 |

錯誤碼與狀態：`UNAUTHENTICATED` 401、`INVALID_CREDENTIALS` 401、`TOO_MANY_ATTEMPTS` 429、`FORBIDDEN` 403、`CSRF` 403、`NOT_FOUND` 404、`DUPLICATE` 409、`RESOURCE_CONFLICT` 409、`PARTICIPANT_CONFLICT` 409、`ALREADY_CANCELLED` 409、`BOOKING_CANCELLED` 409、`VALIDATION` 422、`INACTIVE_REFERENCE` 422、`ORGANIZER_REQUIRED` 422、`DEPARTMENT_CYCLE` 422、`MANAGER_CYCLE` 422、`CANNOT_MODIFY_SELF` 422。

---

### Task 1: 搬舊程式、建立後端骨架

**Files:**
- Move to `legacy/`：`app.py db.py text2sql.py schema.sql llm_schema.sql evals tests pytest.ini Dockerfile`，並複製 `.env.example` 一份到 `legacy/.env.example`
- Create: `backend/requirements.txt`、`backend/pytest.ini`、`backend/app/__init__.py`、`backend/app/config.py`、`backend/tests/conftest.py`、`backend/tests/test_config.py`
- Modify: `docker-compose.yml`（移除整個 `app` 服務與 Ollama 相關環境變數，只留 `postgres` 與 `volumes`）、`.env.example`（只留 `POSTGRES_PASSWORD`、`APP_DB_PASSWORD`、`DATABASE_URL`、`TEST_DATABASE_URL`，值與現在相同）、`README.md`（最上方加一行：重構進行中，舊版在 `legacy/`，設計見 `docs/superpowers/specs/2026-11-20-erp-platform-design.md`）

**Interfaces:**
- Produces: `Config`（dataclass：`databaseUrl: str`、`sessionHours: int = 12`）；`loadConfig() -> Config`，讀環境變數 `DATABASE_URL`，缺少時丟 `RuntimeError`，訊息要說明去 `.env` 設定。
- Produces: conftest 的 session fixture `testDatabaseUrl`（讀 `TEST_DATABASE_URL`，缺少時 `pytest.fail` 並提示）。

- [ ] **Step 1: 搬移並確認** — 執行 `mkdir legacy` 後用 `git mv` 搬上述檔案，`cp .env.example legacy/.env.example`。執行 `git status --short`：預期都是 `R`（renamed），`legacy/.env.example` 為新增。
- [ ] **Step 2: 寫失敗的測試** `backend/tests/test_config.py`：`testLoadConfigReadsDatabaseUrl`（`monkeypatch.setenv("DATABASE_URL", "postgresql://x")` → `loadConfig().databaseUrl == "postgresql://x"` 且 `sessionHours == 12`）、`testLoadConfigRequiresDatabaseUrl`（刪掉環境變數 → `pytest.raises(RuntimeError, match="DATABASE_URL")`）。`backend/pytest.ini`：`pythonpath = .`、`testpaths = tests`。`backend/requirements.txt`：`fastapi>=0.115`、`uvicorn[standard]`、`psycopg[binary]>=3.2`、`argon2-cffi`、`python-dotenv`、`pytest`、`httpx`。
- [ ] **Step 3: 確認失敗** — `cd backend && python -m pip install -r requirements.txt && python -m pytest tests/test_config.py -q`。預期：`ModuleNotFoundError: No module named 'app.config'`。
- [ ] **Step 4: 實作** `backend/app/config.py`；conftest 載入 repo 根目錄的 `.env`（`load_dotenv(Path(__file__).resolve().parents[2] / ".env")`）並定義 `testDatabaseUrl`。更新 `docker-compose.yml`、`.env.example`、README 如上。
- [ ] **Step 5: 驗證** — `cd backend && python -m pytest -q`：預期 `2 passed`，且沒有收集到 `legacy/` 的測試。`docker compose config -q`：預期沒有輸出、結束碼 0。
- [ ] **Step 6: Commit** — `git add legacy backend docker-compose.yml .env.example README.md docs/superpowers && git commit -m "把舊程式搬到 legacy，建立後端骨架與測試基礎"`。

---

### Task 2: 資料庫連線與暫時 schema

**Files:**
- Create: `backend/app/infra/__init__.py`、`backend/app/infra/db.py`
- Modify: `backend/tests/conftest.py`（加 `databaseUrl` fixture）
- Test: `backend/tests/infra/test_db.py`

**Interfaces:**
- Produces: `openDb(databaseUrl: str)`：context manager，回傳 `psycopg.Connection`（`row_factory=dict_row`）；正常離開 commit，例外時 rollback。
- Produces: `temporarySchema(databaseUrl: str, prefix: str)`：context manager，建立 `<prefix>_<8 位隨機>` 的 schema，yield 一個**只看得到它（再加 `public`）**的連線字串（`options=-c search_path=<schema>,public`），離開時 `DROP SCHEMA … CASCADE`。`public` 要留在 search_path，因為 `btree_gist` 的運算子類別裝在 `public`。
- Produces: `ensureExtensions(databaseUrl: str) -> None`：用 autocommit 連線執行 `CREATE EXTENSION IF NOT EXISTS btree_gist SCHEMA public`。擴充是整個資料庫共用的，不能放進會被刪掉的暫時 schema。
- Produces: conftest fixture `databaseUrl`（function scope）：先 `ensureExtensions(testDatabaseUrl)`，再 yield `temporarySchema(testDatabaseUrl, "test")` 的連線字串。

- [ ] **Step 1: 寫失敗的測試** `test_db.py`：`testTemporarySchemaIsolatesTables`（兩個暫時 schema 各建同名表 `t`，各自插入一列，各自只看得到自己的那一列）；`testTemporarySchemaIsDroppedOnExit`（離開後 `information_schema.schemata` 查不到）；`testOpenDbCommitsOnSuccessAndRollsBackOnError`；`testBtreeGistIsAvailable`（`ensureExtensions` 呼叫兩次不出錯，且 `SELECT 1 FROM pg_extension WHERE extname = 'btree_gist'` 有一列）。
- [ ] **Step 2: 確認失敗** — `cd backend && python -m pytest tests/infra/test_db.py -q`。預期：`ModuleNotFoundError: No module named 'app.infra.db'`。
- [ ] **Step 3: 實作** `db.py` 與 `databaseUrl` fixture。`ensureExtensions` 若因權限失敗，在測試錯誤訊息中提示：`docker compose exec postgres psql -U postgres -d schedule_test -c "CREATE EXTENSION IF NOT EXISTS btree_gist SCHEMA public"`（`schedule` 資料庫同樣做一次，並把這句加進 `docker/init/01-create-app-user.sh` 讓新建的資料庫自動有）。`schedule_app` 是這兩個資料庫的擁有者，`btree_gist` 在 PostgreSQL 13 之後是 trusted 擴充，**應該不需要**這個備案，但這點沒有實測過。
- [ ] **Step 4: 確認通過** — 同一個指令。預期 `4 passed`。
- [ ] **Step 5: Commit** — `git commit -m "加上資料庫連線、暫時 schema 與 btree_gist 擴充"`。

---

### Task 3: 錯誤、序列化、登入身分

**Files:**
- Create: `backend/app/infra/errors.py`、`serialize.py`、`actor.py`
- Test: `backend/tests/infra/test_helpers.py`

**Interfaces:**
- Produces: `AppError(Exception)`：`AppError(code: str, message: str, status: int, details: dict | None = None)`，四個屬性同名。
- Produces: `camelizeRow(value)`：遞迴把 dict 的鍵由 snake_case 轉 camelCase，`datetime` 轉 `isoformat(timespec="seconds")`、`date` 轉 `isoformat()`，list 與巢狀 dict 同樣處理；其他值原樣回傳。
- Produces: `parseLocalTime(text: str) -> datetime`：只接受 `YYYY-MM-DDTHH:MM` 或 `YYYY-MM-DDTHH:MM:SS`；含 `Z` 或 `+hh:mm`、格式錯誤時丟 `AppError("VALIDATION", …, 422)`。
- Produces: `Actor`（frozen dataclass）：`userId: int`、`role: str`、`employeeId: int | None`。

- [ ] **Step 1: 寫失敗的測試** `camelizeRow({"start_at": datetime(2026,11,24,10,0), "booking_id": 1, "items": [{"employee_id": 2}]}) == {"startAt": "2026-11-24T10:00:00", "bookingId": 1, "items": [{"employeeId": 2}]}`；`parseLocalTime("2026-11-24T10:00")` 等於對應 datetime；`parseLocalTime` 對 `"2026-11-24T10:00+08:00"`、`"2026-11-24T10:00Z"`、`"2026/11/24 10:00"` 都丟 `AppError`，`code == "VALIDATION"`、`status == 422`。
- [ ] **Step 2: 確認失敗** — `python -m pytest tests/infra/test_helpers.py -q`，預期 `ModuleNotFoundError`。
- [ ] **Step 3: 實作**三個檔案。
- [ ] **Step 4: 確認通過** — 預期 `passed`。
- [ ] **Step 5: Commit** — `git commit -m "加上錯誤型別、camelCase 序列化與登入身分"`。

---

### Task 4: 模組登記、遷移 runner、「不可用」提供者

**Files:**
- Create: `backend/app/infra/registry.py`、`backend/app/infra/migrate.py`、`backend/app/modules/__init__.py`
- Modify: `backend/tests/conftest.py`（加 `migratedUrl` fixture）
- Test: `backend/tests/infra/test_registry.py`、`backend/tests/infra/test_migrate.py`

**Interfaces:**
- Produces: `ModuleManifest`（frozen dataclass）：`name: str`、`title: str`、`dependsOn: tuple[str, ...]`、`permissions: tuple[str, ...]`、`migrationsDir: Path`。
- Produces: `orderModules(manifests: list[ModuleManifest]) -> list[ModuleManifest]`：依 `dependsOn` 排序；依賴不存在或有循環丟 `ValueError`。
- Produces: `registerUnavailabilityProvider(name: str, provider: Callable[[Connection, list[int], datetime, datetime], list[dict]])`、`clearUnavailabilityProviders() -> None`、`collectUnavailability(conn, employeeIds: list[int], startAt: datetime, endAt: datetime) -> list[dict]`：把所有提供者的結果接成一個 list；提供者丟出的例外**不吞掉**。每筆結果至少有 `employeeId`、`reason`、`startAt`、`endAt`。
- Produces: `runMigrations(databaseUrl: str, manifests: list[ModuleManifest]) -> list[str]`：先 `ensureExtensions`，再依 `orderModules` 的順序、每個模組內依檔名排序，逐檔在**一個交易**裡執行，成功才寫入 `schema_migrations(module text, version text, applied_at timestamp, primary key (module, version))`；回傳這次新套用的 `"<module>/<檔名>"` 清單。已套用的跳過；某檔失敗時該檔回復、不記錄，例外往外丟。
- Produces: `app/modules/__init__.py` 的 `allModules: list[ModuleManifest]`，一開始是空 list，之後每個模組的任務把自己的 manifest 加進來。
- Produces: fixture `migratedUrl`：`temporarySchema` 之上再 `runMigrations(url, allModules)`。

- [ ] **Step 1: 寫失敗的測試** `testOrderModulesPutsDependenciesFirst`（`booking` 依賴 `core`、`org`，輸入順序打亂，輸出 `org` 在 `core` 前、`core` 在 `booking` 前）；`testOrderModulesRejectsMissingDependency`、`testOrderModulesRejectsCycle`；`testProvidersAreCollectedAndFlattened`、`testProviderErrorPropagates`；`testRunMigrationsAppliesInOrderAndRecords`（用 `tmp_path` 建兩個假模組，各一個 `.sql`，第二個依賴第一個，結果表都存在、`schema_migrations` 有兩列）；`testRunMigrationsIsIdempotent`（第二次回傳 `[]`）；`testFailedMigrationRollsBackAndIsNotRecorded`（SQL 前半建表、後半語法錯誤 → 丟例外、表不存在、`schema_migrations` 沒有該列）。
- [ ] **Step 2: 確認失敗** — `python -m pytest tests/infra -q`，預期 `ModuleNotFoundError: No module named 'app.infra.registry'`。
- [ ] **Step 3: 實作** `registry.py`、`migrate.py`、`modules/__init__.py`、`migratedUrl`。
- [ ] **Step 4: 確認通過** — 預期全部 `passed`。
- [ ] **Step 5: Commit** — `git commit -m "加上模組登記、遷移 runner 與不可用提供者"`。

---

### Task 5: org 遷移與資料表限制

**Files:**
- Create: `backend/app/modules/org/__init__.py`、`manifest.py`、`migrations/0001_org.sql`
- Modify: `backend/app/modules/__init__.py`（`allModules` 加入 `orgManifest`）
- Test: `backend/tests/org/test_org_schema.py`

**Interfaces:**
- Produces: `orgManifest = ModuleManifest("org", "組織", (), ("org.read", "org.manage"), <migrations 目錄>)`。
- Produces（資料表，欄位依設計文件）：
  - `departments(id identity pk, name text not null unique, parent_id int null → departments, check parent_id is null or parent_id <> id)`
  - `employees(id identity pk, employee_no text not null unique, name text not null, email text null, department_id int not null → departments, job_title text not null, manager_id int null → employees, hired_on date not null, is_active boolean not null default true, left_on date null; check manager_id is null or manager_id <> id; check left_on is null or left_on >= hired_on)`
  - `calendar_days(day date pk, kind text not null check in ('holiday','makeup_workday'), name text not null)`

- [ ] **Step 1: 寫失敗的測試**（用 `migratedUrl` 與 `openDb` 直接下 SQL，驗證資料庫自己的限制）：`testDepartmentCannotBeItsOwnParent`、`testEmployeeCannotBeOwnManager`、`testEmployeeNoMustBeUnique`、`testLeftOnCannotBeBeforeHiredOn`、`testCalendarDayKindIsRestricted`（`'weekend'` 被擋）；以上都用 `pytest.raises(psycopg.errors.CheckViolation 或 UniqueViolation)`。`testEmployeeDefaultsToActive`。
- [ ] **Step 2: 確認失敗** — `python -m pytest tests/org/test_org_schema.py -q`，預期：表不存在（`UndefinedTable`）。
- [ ] **Step 3: 實作**遷移檔、manifest，並更新 `allModules`。
- [ ] **Step 4: 確認通過**，預期 `passed`。
- [ ] **Step 5: Commit** — `git commit -m "加上組織模組的資料表與限制"`。

---

### Task 6: core 遷移與稽核寫入

**Files:**
- Create: `backend/app/modules/core/__init__.py`、`manifest.py`、`migrations/0001_core.sql`、`service.py`
- Modify: `backend/app/modules/__init__.py`
- Test: `backend/tests/core/test_core_schema.py`

**Interfaces:**
- Produces: `coreManifest = ModuleManifest("core", "帳號與稽核", ("org",), ("core.users.manage", "core.audit.read"), …)`。
- Produces（資料表）：
  - `users(id identity pk, email text not null, password_hash text not null, role text not null check in ('employee','manager','hr','admin'), employee_id int null unique → employees, is_active boolean not null default true, last_login_at timestamp null, failed_login_count int not null default 0, locked_until timestamp null, created_at timestamp not null default now())`，另有 `unique index on lower(email)`。
  - `sessions(id_hash text pk, user_id int not null → users on delete cascade, expires_at timestamp not null, created_at timestamp not null default now())`
  - `audit_log(id identity pk, at timestamp not null default now(), user_id int null → users, module text not null, action text not null, entity text not null, entity_id text not null, before jsonb null, after jsonb null)`；遷移最後用 `DO` 區塊對 `current_user` 撤銷 `audit_log` 的 `UPDATE, DELETE, TRUNCATE`（設計文件要求「只能新增」）。
- Produces: `writeAudit(conn, actor: Actor | None, module: str, action: str, entity: str, entityId: int | str, before: dict | None, after: dict | None) -> int`（回傳新列 id；`actor` 為 `None` 時 `user_id` 為空，給指令列用；before/after 轉 JSON 時日期用 `str`、不轉義中文）。
- Produces: `listAudit(conn, module: str | None = None, limit: int = 100, beforeId: int | None = None) -> list[dict]`（camelCase、依 id 由新到舊）。

- [ ] **Step 1: 寫失敗的測試**：`testAuditLogRejectsUpdateAndDelete`（兩者都丟 `psycopg.errors.InsufficientPrivilege`）；`testWriteAuditStoresBeforeAndAfter`（`before={"title": "舊"}`、`after={"title": "新", "day": date(2026,11,24)}` 讀回來內容相同，日期變成字串）；`testListAuditNewestFirstAndPagesByBeforeId`；`testUserEmailIsUniqueIgnoringCase`（`A@x.com` 與 `a@X.com`）；`testUserEmployeeIdIsUnique`；`testRoleCheckRejectsUnknownRole`；`testDeletingUserCascadesSessions`。
- [ ] **Step 2: 確認失敗** — `python -m pytest tests/core/test_core_schema.py -q`，預期 `UndefinedTable`。
- [ ] **Step 3: 實作**遷移、manifest、`writeAudit`、`listAudit`，更新 `allModules`。
- [ ] **Step 4: 確認通過**，預期 `passed`。
- [ ] **Step 5: Commit** — `git commit -m "加上帳號、session、稽核紀錄的資料表與稽核寫入"`。

---

### Task 7: org service

**Files:**
- Create: `backend/app/modules/org/service.py`
- Test: `backend/tests/org/test_org_service.py`

**Interfaces:**
- Consumes: `writeAudit`（任務 6）、`AppError`、`camelizeRow`、`Actor`。
- Produces（都以 `conn` 為第一個參數、回傳 camelCase dict；寫入都呼叫 `writeAudit(module="org")`）：
  - `createDepartment(conn, actor, name: str, parentId: int | None = None) -> dict`、`updateDepartment(conn, actor, departmentId: int, fields: dict) -> dict`（`name`、`parentId`）、`listDepartments(conn) -> list[dict]`
  - `createEmployee(conn, actor, data: dict) -> dict`（`employeeNo`、`name`、`email`、`departmentId`、`jobTitle`、`managerId`、`hiredOn: date`）、`updateEmployee(conn, actor, employeeId: int, fields: dict) -> dict`（可含 `isActive`、`leftOn`）、`getEmployee(conn, employeeId: int) -> dict`、`listEmployees(conn, includeInactive: bool = False) -> list[dict]`
  - `listSubordinateIds(conn, employeeId: int) -> set[int]`：所有層級的下屬、不含自己；主管鏈有循環時也要結束（遞迴查詢用 `UNION`）。
  - `upsertCalendarDay(conn, actor, day: date, kind: str, name: str) -> dict`、`deleteCalendarDay(conn, actor, day: date) -> None`、`listCalendarDays(conn, start: date, end: date) -> list[dict]`
- 錯誤：唯一性衝突 → `DUPLICATE` 409；找不到 → `NOT_FOUND` 404；欄位不合（空名稱、`kind` 不合法）→ `VALIDATION` 422；部門或主管的上層鏈會形成循環 → `DEPARTMENT_CYCLE`／`MANAGER_CYCLE` 422。

- [ ] **Step 1: 寫失敗的測試**：`testCreateEmployeeWritesAudit`（稽核有一列 `module="org"`、`action="createEmployee"`、`after` 內有 `employeeNo`）；`testDuplicateEmployeeNoRaisesDuplicate`；`testListEmployeesHidesInactiveByDefault`（停用後預設列表沒有，`includeInactive=True` 有）；`testListSubordinateIdsCoversAllLevels`（A 管 B、B 管 C → A 的下屬是 `{B, C}`，C 的下屬是空集合）；`testListSubordinateIdsSurvivesCycle`（資料庫層面把 A、B 互設為主管後呼叫不會卡住，結果不含自己）；`testManagerCycleIsRejected`（把 A 的主管設成 A 的下屬 → `MANAGER_CYCLE`）；`testDepartmentCycleIsRejected`；`testUpsertCalendarDayReplacesExisting`；`testBlankNameIsValidationError`。
- [ ] **Step 2: 確認失敗** — `python -m pytest tests/org/test_org_service.py -q`，預期 `ModuleNotFoundError`。
- [ ] **Step 3: 實作** `service.py`。
- [ ] **Step 4: 確認通過**，預期 `passed`。
- [ ] **Step 5: Commit** — `git commit -m "加上組織模組的 service：部門、員工、行事曆、下屬查詢"`。

---

### Task 8: core 密碼、帳號與 session

**Files:**
- Create: `backend/app/modules/core/security.py`
- Modify: `backend/app/modules/core/service.py`
- Test: `backend/tests/core/test_security.py`、`backend/tests/core/test_auth_service.py`

**Interfaces:**
- Produces（`security.py`）：`hashPassword(password: str) -> str`（`argon2id`）、`verifyPassword(passwordHash: str, password: str) -> bool`、`newSessionToken() -> str`（`secrets.token_urlsafe(32)`）、`hashToken(token: str) -> str`（sha256 十六進位）。
- Produces（`service.py`，`conn` 為第一個參數）：
  - `createUser(conn, actor: Actor | None, email: str, password: str, role: str, employeeId: int | None = None) -> dict`：email 去前後空白；密碼長度 8 到 128；role 要合法；稽核裡**不能出現密碼或雜湊**。
  - `authenticate(conn, email: str, password: str, now: datetime | None = None) -> dict`：email 去空白、不分大小寫；成功時歸零 `failed_login_count`、寫 `last_login_at`；失敗丟 `INVALID_CREDENTIALS` 401（email 不存在與密碼錯誤訊息相同，且都要做一次雜湊比對避免從時間差猜出帳號）；連續失敗 5 次鎖 15 分鐘，鎖定期間（連密碼正確也）丟 `TOO_MANY_ATTEMPTS` 429；停用的帳號當作 `INVALID_CREDENTIALS`。
  - `createSession(conn, userId: int, hours: int = 12, now: datetime | None = None) -> str`（只存 token 的雜湊）、`getSessionActor(conn, token: str, now: datetime | None = None) -> Actor | None`（過期、帳號停用、token 不存在都回 `None`）、`deleteSession(conn, token: str) -> None`
  - `changePassword(conn, actor: Actor, currentPassword: str, newPassword: str) -> None`、`resetPassword(conn, actor: Actor, userId: int, newPassword: str) -> None`：兩者都刪掉該使用者所有 session；`resetPassword` 同時解除鎖定。
  - `updateUser(conn, actor: Actor, userId: int, fields: dict) -> dict`（`role`、`isActive`、`employeeId`）：停用時刪掉該使用者所有 session；改自己的角色或停用自己 → `CANNOT_MODIFY_SELF` 422（避免鎖死唯一的管理員）。
  - `listUsers(conn) -> list[dict]`（不含雜湊）、`getUser(conn, userId: int) -> dict`

- [ ] **Step 1: 寫失敗的測試**：`testHashPasswordRoundTrip`（正確通過、錯誤失敗、同一密碼兩次雜湊不同）；`testTokenHashIsStableAndNotTheToken`。`test_auth_service.py`：`testAuthenticateIgnoresEmailCaseAndWhitespace`（`"  Admin@X.com "` 登入以 `admin@x.com` 建立的帳號成功）；`testWrongPasswordAndUnknownEmailGiveSameError`（同 code 同 message）；`testLockAfterFiveFailures`（第 6 次即使密碼正確也 `TOO_MANY_ATTEMPTS`；用 `now` 前進 16 分鐘後成功）；`testSuccessResetsFailureCount`；`testSessionRoundTrip`；`testExpiredSessionReturnsNone`（`now` 超過 12 小時）；`testDeactivatedUserSessionReturnsNone`；`testDeactivatingUserDeletesSessions`；`testChangePasswordRequiresCurrentAndDropsSessions`；`testResetPasswordUnlocksAccount`；`testPasswordLengthLimits`（7 字元與 129 字元都 `VALIDATION`，含中文的 8 字元通過）；`testCannotModifySelfRoleOrActive`；`testAuditNeverContainsPassword`（把 `audit_log` 的 `after` 轉成字串，不含密碼也不含 `$argon2`）。
- [ ] **Step 2: 確認失敗** — `python -m pytest tests/core -q`，預期 `ModuleNotFoundError`／`ImportError`。
- [ ] **Step 3: 實作**。
- [ ] **Step 4: 確認通過**，預期 `passed`。
- [ ] **Step 5: Commit** — `git commit -m "加上密碼雜湊、登入鎖定、session 與帳號管理 service"`。

---

### Task 9: booking 遷移與資料表限制

**Files:**
- Create: `backend/app/modules/booking/__init__.py`、`manifest.py`、`migrations/0001_booking.sql`
- Modify: `backend/app/modules/__init__.py`
- Test: `backend/tests/booking/test_booking_schema.py`

**Interfaces:**
- Produces: `bookingManifest = ModuleManifest("booking", "資源預約", ("org", "core"), ("booking.read", "booking.write", "booking.writeAny", "booking.resources.manage"), …)`。
- Produces（資料表）：
  - `resources(id identity pk, name text not null unique, kind text not null check in ('room','equipment','vehicle'), location text null, capacity int null check capacity > 0, features text[] not null default '{}', is_active boolean not null default true, note text null)`
  - `bookings(id identity pk, title text not null check btrim(title) <> '', category text not null, start_at timestamp not null, end_at timestamp not null, status text not null default 'confirmed' check in ('confirmed','cancelled'), note text null, created_by int not null → users, created_at timestamp not null default now(), check end_at > start_at)`
  - `booking_resources(booking_id → bookings on delete cascade, resource_id → resources, during tsrange not null, is_active boolean not null, primary key (booking_id, resource_id), exclude using gist (resource_id with =, during with &&) where (is_active))`
  - `booking_participants(booking_id → bookings on delete cascade, employee_id → employees, role text not null check in ('organizer','attendee'), primary key (booking_id, employee_id))`，另有 `unique index (booking_id) where role = 'organizer'`。
- 兩個 trigger：`booking_resources` 的 BEFORE INSERT 從所屬的 `bookings` 帶入 `during = tsrange(start_at, end_at, '[)')` 與 `is_active = (status = 'confirmed')`；`bookings` 的 AFTER UPDATE OF `start_at, end_at, status` 把同樣兩個值同步到它的 `booking_resources`。「至少有一個主辦人」資料庫不管，由任務 10 的 service 保證；資料庫只保證至多一個。

- [ ] **Step 1: 寫失敗的測試**（直接下 SQL，`migratedUrl`，先插入 org／core 需要的基本資料）：`testExclusionRejectsOverlappingActiveBookings`（同資源 10:00–11:00 與 10:30–11:30 → `psycopg.errors.ExclusionViolation`）；`testAdjacentBookingsAreAllowed`（10:00–11:00 與 11:00–12:00 都成功）；`testDifferentResourcesMayOverlap`；`testCancelledBookingDoesNotBlock`（第一筆改 `status='cancelled'` 後，第二筆同時段成功）；`testChangingBookingTimeSyncsDuring`（改 `bookings.end_at` 後 `booking_resources.during` 跟著變）；`testMovingIntoConflictIsRejected`（把一筆移到另一筆的時段 → `ExclusionViolation`）；`testReactivatingCancelledBookingIntoConflictIsRejected`；`testSecondOrganizerRejected`（`UniqueViolation`）；`testEndMustBeAfterStart`、`testBlankTitleRejected`（`CheckViolation`）；`testBookingMayCrossMidnight`。
- [ ] **Step 2: 確認失敗** — `python -m pytest tests/booking/test_booking_schema.py -q`，預期 `UndefinedTable`。
- [ ] **Step 3: 實作**遷移與 manifest，更新 `allModules`。
- [ ] **Step 4: 確認通過**，預期 `passed`。
- [ ] **Step 5: Commit** — `git commit -m "加上資源預約的資料表與排除限制"`。

---

### Task 10: booking service

**Files:**
- Create: `backend/app/modules/booking/service.py`
- Test: `backend/tests/booking/test_booking_service.py`、`backend/tests/booking/test_booking_concurrency.py`

**Interfaces:**
- Consumes: `writeAudit`、`collectUnavailability`、`hasPermission`（任務 11 才建立；本任務先在 `infra/permissions.py` 建最小版 `hasPermission(role: str, permission: str) -> bool`，任務 11 補完角色表）、`AppError`、`camelizeRow`、`Actor`。
- Produces:
  - `BookingInput`（dataclass）：`title: str`、`category: str`、`startAt: datetime`、`endAt: datetime`、`resourceIds: list[int]`、`participantEmployeeIds: list[int]`、`organizerEmployeeId: int | None = None`、`note: str | None = None`、`acknowledgeWarnings: bool = False`
  - `createResource(conn, actor, data: dict) -> dict`、`updateResource(conn, actor, resourceId: int, fields: dict) -> dict`、`listResources(conn, includeInactive: bool = False) -> list[dict]`
  - `createBooking(conn, actor: Actor, data: BookingInput) -> dict`
  - `updateBooking(conn, actor: Actor, bookingId: int, fields: dict) -> dict`（`fields` 可含 `BookingInput` 的任何欄位；未提供的保持不變）
  - `cancelBooking(conn, actor: Actor, bookingId: int) -> dict`
  - `getBooking(conn, bookingId: int) -> dict`
  - `listBookings(conn, rangeStart: datetime, rangeEnd: datetime, resourceId: int | None = None, employeeId: int | None = None, includeCancelled: bool = False) -> list[dict]`：回傳「與範圍重疊」的預約（`start_at < rangeEnd and end_at > rangeStart`），依 `start_at, id` 排序。
  - `getSummary(conn, now: datetime) -> dict`：`{"todayBookings": [...], "nextBooking": dict | None, "resourceStatus": [{"resourceId", "name", "kind", "currentBooking": dict | None}], "bookingCount": int, "resourceCount": int}`；只算 `confirmed` 與啟用中的資源；「今天」是 `now` 當天 00:00 到隔天 00:00。
- 預約 dict：`id, title, category, startAt, endAt, status, note, createdBy, createdAt, resources: [{id, name, kind}], participants: [{employeeId, name, role}]`。
- 行為規則：
  - 主辦人 = `organizerEmployeeId`，沒給就用 `actor.employeeId`；兩者都沒有 → `ORGANIZER_REQUIRED`。主辦人一定會被加入參加者並標為 `organizer`。資源可以是空的。
  - 資源與參加者 id 先去重；用到停用的資源或員工 → `INACTIVE_REFERENCE`；`endAt <= startAt`、標題空白 → `VALIDATION`。
  - 先用 `findResourceConflicts` 查撞期並回報 `RESOURCE_CONFLICT`（`details.conflicts` 每筆有 `bookingId, title, startAt, endAt, resourceId, resourceName`）；寫入時仍可能因並行撞期而由資料庫的 `ExclusionViolation` 擋下，這時在**巢狀交易（savepoint）**裡回復後重新查詢細節，同樣丟 `RESOURCE_CONFLICT`。
  - 參加者警告：同時段別的 `confirmed` 預約，加上 `collectUnavailability` 的結果；有警告且 `acknowledgeWarnings` 為假 → `PARTICIPANT_CONFLICT`（`details.conflicts` 每筆有 `employeeId, name, reason, startAt, endAt`，來自別的預約時另有 `bookingId, title`）。資源撞期優先於參加者警告。
  - 修改與取消：建立者本人，或 `hasPermission(actor.role, "booking.writeAny")` 才行，否則 `FORBIDDEN` 403。修改時的衝突檢查要排除預約自己。已取消的預約不能修改（`BOOKING_CANCELLED`）、不能再取消（`ALREADY_CANCELLED`）。
  - 修改順序：先 `UPDATE bookings`（trigger 同步既有的 `booking_resources`），再增減 `booking_resources`／`booking_participants`。
  - 預約的建立、修改、取消，以及資源的建立與修改，都寫稽核（`module="booking"`，`before`／`after` 為該筆的 dict）。

- [ ] **Step 1: 寫失敗的測試** `test_booking_service.py`（先寫 helper 建立 org 員工、使用者、資源）：`testCreateBookingStoresResourcesAndParticipants`；`testAdjacentBookingsDoNotConflict`；`testOverlappingResourceRaisesResourceConflictWithDetails`（`details.conflicts[0]["title"]` 等於先建立的那筆）；`testBookingMayCrossMidnight`（22:00 到隔天 06:00，用隔天的範圍 `listBookings` 找得到）；`testParticipantOverlapWarnsUnlessAcknowledged`（第二次帶 `acknowledgeWarnings=True` 成功）；`testRegisteredUnavailabilityProviderProducesWarning`（`registerUnavailabilityProvider` 一個假提供者回傳「請假」，建立時 `PARTICIPANT_CONFLICT` 且 `reason == "請假"`；測試結束 `clearUnavailabilityProviders()`）；`testResourceConflictWinsOverParticipantWarning`；`testUpdateExcludesBookingItself`（只改 `note` 不撞期；移到別人的時段才 `RESOURCE_CONFLICT`）；`testCancelFreesResource`；`testCancelTwiceRaisesAlreadyCancelled`、`testUpdateCancelledRaises`；`testOnlyCreatorOrWriteAnyMayModify`（employee 改別人的 → `FORBIDDEN`；hr 可以）；**Review Focus**：`testDuplicateResourceAndParticipantIdsAreDeduplicated`（`resourceIds=[1,1]`、參加者含主辦人重複 → 成功且各一列）、`testInactiveResourceOrEmployeeIsRejected`、`testAccountWithoutEmployeeNeedsOrganizer`（admin 無 `employeeId` → `ORGANIZER_REQUIRED`；指定 `organizerEmployeeId` 則成功）；`testEndNotAfterStartIsValidationError`；`testAuditRowsForCreateUpdateCancel`；`testListBookingsFiltersByResourceAndEmployeeAndHidesCancelled`；`testSummaryUsesNowForTodayNextAndCurrent`（固定 `now`，驗證 `nextBooking` 是第一個開始時間晚於 `now` 的、`currentBooking` 是正在進行的）。
  `test_booking_concurrency.py`：`testConcurrentBookingsOfSameResourceOnlyOneSucceeds`——兩條執行緒各自 `openDb(migratedUrl)`，用 `threading.Barrier(2)` 同時 `createBooking` 同一資源、同一時段；重複 10 輪（每輪新資源），每輪恰好一個成功、一個 `AppError` 且 `code == "RESOURCE_CONFLICT"`。
- [ ] **Step 2: 確認失敗** — `python -m pytest tests/booking -q`，預期 `ModuleNotFoundError: No module named 'app.modules.booking.service'`。
- [ ] **Step 3: 實作** `service.py` 與 `infra/permissions.py` 的最小版 `hasPermission`。
- [ ] **Step 4: 確認通過** — 預期 `passed`。並行測試再連續跑 3 次（避免偶然通過）：`for i in 1 2 3; do python -m pytest tests/booking/test_booking_concurrency.py -q || break; done`，預期 3 次都 `passed`。
- [ ] **Step 5: Commit** — `git commit -m "加上資源預約 service：衝突、警告、修改、取消、摘要"`。

---

### Task 11: 權限表、HTTP 基礎、登入 API

**Files:**
- Create: `backend/app/infra/http.py`、`backend/app/main.py`、`backend/app/modules/core/router.py`
- Modify: `backend/app/infra/permissions.py`（補完角色表）
- Test: `backend/tests/infra/test_permissions.py`、`backend/tests/core/test_auth_api.py`、`backend/tests/conftest.py`（加 `client`、`makeUser` helper）

**Interfaces:**
- Produces（`permissions.py`）：`rolePermissions: dict[str, frozenset[str]]`——`employee` 與 `manager`：`org.read, booking.read, booking.write`；`hr`：再加 `org.manage, booking.writeAny`；`admin`：再加 `booking.resources.manage, core.users.manage, core.audit.read`。`hasPermission(role, permission) -> bool`；`permissionsFor(role) -> frozenset[str]`。
- Produces（`http.py`）：`getConn(request)`：FastAPI 依賴，從 `request.app.state.databaseUrl` 開連線，請求成功 commit、丟例外 rollback；`getActor(request, conn) -> Actor`：讀 cookie `sid`，找不到或失效 → `UNAUTHENTICATED` 401；`requirePermission(permission: str)`：依賴工廠，沒有權限 → `FORBIDDEN` 403；CSRF 中介層：非 `GET/HEAD/OPTIONS` 請求沒有標頭 `X-App-Client: web` → `CSRF` 403；`AppError` 與請求驗證錯誤的處理器，輸出統一的錯誤格式（驗證錯誤 → `VALIDATION` 422，`details` 放欄位清單）。
- Produces（`main.py`）：`createApp(databaseUrl: str) -> FastAPI`（`app.state.databaseUrl`；掛上 CSRF 中介層與錯誤處理器；`allModules` 的每個模組，用 `importlib.import_module(f"app.modules.{manifest.name}.router")` 載入、取其中的 `router`（`APIRouter`）掛在 `/api/<name>`；該模組沒有 `router.py`（`ModuleNotFoundError` 且缺的正是這個模組）就略過；`GET /api/modules`）、`createAppFromEnv() -> FastAPI`（`loadConfig()` 後呼叫 `createApp`，給 `uvicorn --factory` 用）。
- Produces（登入 API，`core/router.py`）：`POST /api/auth/login`（body `email`、`password`；成功設 cookie `sid`：`HttpOnly`、`SameSite=Lax`、`Path=/`、`Max-Age=sessionHours*3600`；回 `{"user": {"id", "email", "role", "employeeId", "employeeName"}}`）、`POST /api/auth/logout`（刪 session、清 cookie，204）、`GET /api/auth/me`（同 `user` 格式）、`POST /api/auth/password`（body `currentPassword`、`newPassword`，成功 204、清 cookie）。`GET /api/modules` 回傳 `[{"name", "title", "permissions": [使用者擁有、且屬於該模組的權限]}]`，沒有任何該模組權限的模組不列出。
- conftest：`client` fixture（`TestClient(createApp(migratedUrl))`，預設標頭 `X-App-Client: web`）；`makeUser(role, email=..., employee=False) -> (userId, password)` helper（直接用 service 建立）；`loginAs(client, role)` helper。

- [ ] **Step 1: 寫失敗的測試** `test_permissions.py`：依設計文件的權限表做 `pytest.mark.parametrize`，**每一格**（4 個角色 × `org.read, org.manage, booking.read, booking.write, booking.writeAny, booking.resources.manage, core.users.manage, core.audit.read`）斷言 `hasPermission` 等於表上的 ✓／—。`test_auth_api.py`：`testLoginSetsHttpOnlySameSiteCookie`（`set-cookie` 含 `HttpOnly`、`SameSite=lax`）；`testLoginWithWrongPasswordIs401WithErrorFormat`（`response.json()["error"]["code"] == "INVALID_CREDENTIALS"`）；`testLockedAccountIs429`；`testMeRequiresSession`（無 cookie → 401 `UNAUTHENTICATED`）；`testPostWithoutCsrfHeaderIs403`（`client.headers` 移除標頭後 POST 任何路徑 → `CSRF`）；`testGetDoesNotNeedCsrfHeader`；`testLogoutInvalidatesSession`（登出後同一個 cookie 打 `/api/auth/me` → 401）；`testChangePasswordClearsSessionAndOldPasswordFails`；`testModulesListFiltersByPermission`（employee 看到 `org`、`booking`，看不到 `core`；admin 三個都看到）；**Review Focus**：`testDeactivatedUserCookieIsRejected`（登入後由管理員身分停用該帳號，原 cookie 打 `/api/auth/me` → 401）。
- [ ] **Step 2: 確認失敗** — `python -m pytest tests/infra/test_permissions.py tests/core/test_auth_api.py -q`，預期 `ImportError`。
- [ ] **Step 3: 實作**。
- [ ] **Step 4: 確認通過**，預期 `passed`；再跑一次 `python -m pytest -q` 確認前面任務沒被影響。
- [ ] **Step 5: Commit** — `git commit -m "加上權限表、HTTP 基礎與登入 API"`。

---

### Task 12: org API

**Files:**
- Create: `backend/app/modules/org/router.py`
- Test: `backend/tests/org/test_org_api.py`

**Interfaces:**
- Consumes: 任務 7 的 service、任務 11 的 `getConn`／`getActor`／`requirePermission`。
- Produces：「API 清單」中 `/api/org/...` 的全部路由。讀取需要 `org.read`，寫入需要 `org.manage`。請求用 pydantic 模型驗證（欄位 camelCase），日期欄位 `YYYY-MM-DD`；回應是 service 回傳的 camelCase dict。建立成功回 201，`PATCH`／`PUT` 回 200，`DELETE` 回 204。

- [ ] **Step 1: 寫失敗的測試**：`testEmployeeCanReadButNotWrite`（employee `GET /api/org/employees` 200、`POST` 403 `FORBIDDEN`）；`testHrCanCreateDepartmentAndEmployee`（201，回應含 `id`、`employeeNo`，鍵是 camelCase、日期是字串）；`testDuplicateEmployeeNoIs409`；`testManagerCycleIs422`；`testInvalidBodyIs422WithValidationCode`（缺 `name`）；`testDeactivateEmployeeViaPatch`（`isActive: false` 後預設列表沒有）；`testCalendarDayPutAndDelete`；`testUnauthenticatedIs401`。
- [ ] **Step 2: 確認失敗** — `python -m pytest tests/org/test_org_api.py -q`，預期 404（路由不存在）。
- [ ] **Step 3: 實作** `router.py`，模組內匯出名為 `router` 的 `APIRouter`（`createApp` 依任務 11 的規則自動掛上，不需要改 `main.py`）。
- [ ] **Step 4: 確認通過**，預期 `passed`。
- [ ] **Step 5: Commit** — `git commit -m "加上組織模組的 API"`。

---

### Task 13: booking API

**Files:**
- Create: `backend/app/modules/booking/router.py`
- Test: `backend/tests/booking/test_booking_api.py`

**Interfaces:**
- Consumes: 任務 10 的 service、`parseLocalTime`（任務 3）、任務 11 的依賴。
- Produces：「API 清單」中 `/api/booking/...` 的全部路由。`GET /api/booking/bookings` 的查詢參數：`from`、`to`（`parseLocalTime` 格式，必填）、`resourceId`、`employeeId`、`includeCancelled`。請求 body 用 pydantic 驗證，時間欄位交給 `parseLocalTime`（含時區位移 → 422）。`POST /api/booking/bookings` 成功回 201；`acknowledgeWarnings` 在 body 裡。資源管理需要 `booking.resources.manage`；預約的建立、修改、取消需要 `booking.write`（再由 service 檢查「自己建立的」）。

- [ ] **Step 1: 寫失敗的測試**（用 `client`、`loginAs`）：`testCreateBookingReturns201WithResourcesAndParticipants`；`testResourceConflictIs409WithDetails`（`error.code == "RESOURCE_CONFLICT"`、`error.details.conflicts[0].title`）；`testParticipantConflictThenAcknowledgeRetry`（第一次 409 `PARTICIPANT_CONFLICT`，同一 body 加 `acknowledgeWarnings: true` 重送 → 201）；`testCrossMidnightBookingAccepted`；`testTimeWithTimezoneOffsetIs422`（`"2026-11-24T10:00+08:00"`）；`testEndBeforeStartIs422`；`testNonCreatorPatchIs403AndHrPatchIs200`；`testCancelThenRebookSameSlot`；`testEmployeeCannotCreateResourceButAdminCan`；`testListFiltersAndRequiresRange`（缺 `from` → 422）；`testSummaryEndpointShape`（鍵：`todayBookings, nextBooking, resourceStatus, bookingCount, resourceCount`）；`testAdminWithoutEmployeeMustPassOrganizer`（`ORGANIZER_REQUIRED` 422）。
- [ ] **Step 2: 確認失敗** — `python -m pytest tests/booking/test_booking_api.py -q`，預期 404。
- [ ] **Step 3: 實作** `router.py`，模組內匯出名為 `router` 的 `APIRouter`。
- [ ] **Step 4: 確認通過**，預期 `passed`。
- [ ] **Step 5: Commit** — `git commit -m "加上資源預約的 API"`。

---

### Task 14: 帳號管理 API、稽核 API、指令列

**Files:**
- Modify: `backend/app/modules/core/router.py`
- Create: `backend/app/cli.py`
- Test: `backend/tests/core/test_admin_api.py`、`backend/tests/test_cli.py`

**Interfaces:**
- Produces（router）：`GET/POST /api/core/users`、`PATCH /api/core/users/{id}`、`POST /api/core/users/{id}/password`（body `newPassword`）需要 `core.users.manage`；`GET /api/core/audit`（查詢參數 `module`、`limit`、`beforeId`）需要 `core.audit.read`。
- Produces（`cli.py`，執行 `python -m app.cli <指令>`，在 `backend/` 目錄）：
  - `migrateCommand(databaseUrl: str) -> list[str]`：呼叫 `runMigrations(databaseUrl, allModules)`，印出新套用的項目。
  - `createUserCommand(databaseUrl: str, email: str, role: str, password: str, employeeNo: str | None = None) -> int`：建立帳號並回傳 id（`employeeNo` 給了就連到該員工）；稽核的 `actor` 為 `None`。`main()` 解析 `--email`、`--role`、`--employee-no`，密碼用 `getpass` 輸入兩次、不接受命令列參數。
  - `seedDemoCommand(databaseUrl: str) -> None`：資料庫沒有任何員工時，寫入 3 個部門、4 位員工（含一條主管鏈）、4 個資源（2 間會議室、1 個設備、1 台公務車）、幾筆本週與下週的排程；**不建立任何使用者**。已有員工時丟 `AppError("NOT_EMPTY", …, 409)`，不覆寫。
  
- [ ] **Step 1: 寫失敗的測試**：`testNonAdminCannotManageUsers`（hr 打 `/api/core/users` → 403）；`testAdminCreatesUserAndTheyCanLogin`；`testAdminDeactivatesUserAndSessionsDie`；`testAdminCannotDeactivateSelf`（`CANNOT_MODIFY_SELF`）；`testAdminResetsPassword`；`testUserListNeverIncludesPasswordHash`；`testAuditEndpointFiltersByModuleAndOnlyAdmin`；`test_cli.py`：`testMigrateCommandAppliesThenNoop`（第二次回傳 `[]`）；`testCreateUserCommandCreatesAdminWhoCanAuthenticate`；`testCreateUserCommandLinksEmployeeNo`；`testSeedDemoPopulatesAndRefusesSecondRun`（第二次 `NOT_EMPTY`）；`testSeedDemoCreatesNoUsers`。
- [ ] **Step 2: 確認失敗** — `python -m pytest tests/core/test_admin_api.py tests/test_cli.py -q`，預期 404／`ModuleNotFoundError`。
- [ ] **Step 3: 實作**。
- [ ] **Step 4: 確認通過**，預期 `passed`。
- [ ] **Step 5: Commit** — `git commit -m "加上帳號管理與稽核 API、指令列"`。

---

### Task 15: 整合驗證與後端說明

**Files:**
- Create: `backend/README.md`（怎麼跑測試、怎麼遷移、怎麼建管理員、怎麼啟動、API 清單位置）

- [ ] **Step 1: 全部測試** — `cd backend && python -m pytest -q`。預期：全部通過，沒有被跳過的測試。
- [ ] **Step 2: 手動冒煙測試前，先取得使用者同意** — 開發資料庫 `schedule` 裡還有舊版的資料表（`resources`、`events`、`employees`…），名稱會跟新結構衝突。**向使用者確認後**才執行 `docker compose down -v && docker compose up -d --wait postgres`（會清空資料庫，裡面只有舊的示範資料）。
- [ ] **Step 3: 遷移與建立管理員** — `cd backend && python -m app.cli migrate`，預期印出 `org/0001_org.sql`、`core/0001_core.sql`、`booking/0001_booking.sql`。再 `python -m app.cli createUser --email admin@example.com --role admin` 並輸入密碼；`python -m app.cli seedDemo`。
- [ ] **Step 4: 啟動並用 curl 走一輪** — `uvicorn app.main:createAppFromEnv --factory --host 127.0.0.1 --port 8000`；另一個終端機：以 `curl -c jar -H "X-App-Client: web" -H "Content-Type: application/json" -d '{"email":"admin@example.com","password":"<密碼>"}' http://127.0.0.1:8000/api/auth/login` 登入（預期 200，回傳 `user`），再 `curl -b jar http://127.0.0.1:8000/api/booking/summary`（預期 200，鍵為 `todayBookings` 等）；不帶標頭的 `POST` 預期 403 `CSRF`；`http://127.0.0.1:8000/docs` 能開啟自動產生的 API 文件。
- [ ] **Step 5: 確認只綁本機** — 預期從區網的其他裝置連不到 `8000`（啟動指令用的是 `127.0.0.1`）。
- [ ] **Step 6: Commit** — `git add backend/README.md && git commit -m "加上後端說明"`。

---

## 之後（不在這份計畫內）

- **前端計畫**（階段 2）：依「API 清單」做 React 外殼，把 `prototype/` 放進 repo 當參考，補齊每個寫入動作的入口。
- **切換計畫**（階段 3）：後端 Dockerfile（含前端建置）、`docker-compose.yml` 加上新服務、更新根目錄 README、移除舊的 Streamlit 容器設定。
