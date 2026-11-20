# 後端（FastAPI + PostgreSQL）

請假排班系統的後端：組織、資源預約、登入與角色、稽核。設計見 `docs/superpowers/specs/2026-11-20-erp-platform-design.md`，實作計畫見 `docs/superpowers/plans/2026-11-20-erp-platform-backend.md`（裡面的「API 清單」是前端要逐項對照的核對表）。

下面的指令都在 **`backend/` 目錄**執行，設定檔是 repo 根目錄的 `.env`（從 `.env.example` 複製，密碼改成自己的值）。

## 第一次使用

```powershell
docker compose up -d --wait postgres      # 在 repo 根目錄；PostgreSQL 只綁 127.0.0.1:5433
cd backend
python -m pip install -r requirements.txt
python -m app.cli migrate                  # 建立資料表（已套用過的會跳過）
python -m app.cli createUser --email admin@example.com --role admin   # 會互動輸入兩次密碼
python -m app.cli seedDemo                 # 選用：寫入示範的部門、員工、資源、排程
```

- 密碼只能互動輸入，不接受命令列參數（命令列會留在 shell 歷史裡）。
- `seedDemo` 只能用在沒有任何員工的開發資料庫，而且要先有管理員（示範排程的建立者）。它不會建立帳號。
- 資料庫裡如果還有**舊版**（Streamlit 版本）的資料表，名稱會和新結構衝突，`migrate` 會失敗。舊版只有示範資料，可以用 `docker compose down -v` 清掉整個資料庫再重來（會刪除資料庫裡的所有資料）。

## 啟動

```powershell
uvicorn app.main:createAppFromEnv --factory --host 127.0.0.1 --port 8000
```

- 自動產生的 API 文件：<http://127.0.0.1:8000/docs>
- 一定要寫 `--host 127.0.0.1`：目前沒有 HTTPS，cookie 沒有 `Secure`，只能給本機使用。
- 所有非 GET 請求都要帶標頭 `X-App-Client: web`（擋跨站請求）；登入後的 session 放在 HttpOnly cookie `sid`。
- 錯誤一律是 `{ "error": { "code", "message", "details" } }`。

## 測試

```powershell
python -m pytest -q
```

測試用真的 PostgreSQL（`.env` 的 `TEST_DATABASE_URL`），每個測試建立自己的暫時 schema、跑完整套遷移後再刪掉，不會碰到開發資料。完整跑一次要好幾分鐘（密碼雜湊與每個測試都重建資料表）。

## 結構

```
app/
  config.py  main.py  cli.py
  infra/      連線與暫時 schema、錯誤、遷移 runner、模組登記、權限表、HTTP 基礎
  modules/
    org/      部門、員工、行事曆
    core/     帳號、登入（session）、稽核紀錄
    booking/  資源、排程（資源撞期由資料庫的排除限制擋下）
```

### 新增一個模組

1. 建立 `app/modules/<名稱>/`：`manifest.py`（名稱、依賴、權限、遷移資料夾）、`migrations/0001_….sql`、`service.py`、`router.py`（匯出名為 `router` 的 `APIRouter`）。
2. 把 manifest 加進 `app/modules/__init__.py` 的 `allModules`；路由會自動掛在 `/api/<名稱>`，遷移會依 `dependsOn` 排序。
3. 把新的權限加進 `app/infra/permissions.py` 的角色表，並在 `tests/infra/test_permissions.py` 補上那一格。

「不可用」提供者：請假、排班這類模組可以用 `registerUnavailabilityProvider` 登記，資源預約檢查參加者時就會自動帶出警告，不用改資源預約的程式。

## 已知限制

- 時間都是不帶時區的本地時間。程式用 Python 的 `datetime.now()` 當作「現在」；之後放進容器時要設好 `TZ`（例如 `Asia/Taipei`），否則「今天」會以 UTC 計算。
- 登入失敗 5 次鎖 15 分鐘；session 12 小時；密碼 8 到 128 字元。
