# 請假排班系統

員工請假與排班的內部系統。目前有組織（部門、員工、行事曆）、資源預約（會議室、設備、公務車，同一資源同一時段不會被重複預約）、登入與角色、稽核紀錄；請假與排班模組之後再加。

## 啟動

需要 Docker。

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }   # 已經有 .env 就不要蓋掉；新的 .env 要把兩組 change-me 密碼改成自己的值（只用英文和數字）
docker compose up -d --build --wait        # 第一次要建置映像檔；第一次建立資料庫可能要好幾分鐘
docker compose exec app python -m app.cli createUser --email admin@example.com --role admin   # 建立第一個管理員，會互動輸入兩次密碼
docker compose exec app python -m app.cli seedDemo                                            # 選用：示範的部門、員工、資源、排程
```

打開 <http://127.0.0.1:8000/>，用剛建的管理員登入。

- 只綁 `127.0.0.1`：目前沒有 HTTPS，不能對區網或外網開放。
- 更新程式後再執行一次 `docker compose up -d --build --wait`，資料庫遷移會自動套用，資料不會被清掉。
- **啟動失敗**：`--wait` 會回報 unhealthy；看原因用 `docker compose logs app`。不加 `--wait` 的話，失敗時容器只會不斷重啟，畫面不會有提示。
- 如果資料庫裡還有**舊版**（Streamlit）的資料表，遷移會因為名稱撞名而失敗，要先 `docker compose down -v` 清掉資料庫（會刪除所有資料；舊版只有示範資料）。
- 容器與手動啟動的 uvicorn 都用 8000，同時只能跑一個。要改 port，在 `.env` 加上 `APP_PORT`、`POSTGRES_PORT`（見 `.env.example`）。
- 時間用台灣時間（容器的 `TZ=Asia/Taipei`）。
- 停止：`docker compose stop`；連資料庫一起清掉：`docker compose down -v`（會刪除所有資料）。

## 開發

- 後端（FastAPI + PostgreSQL）：見 `backend/README.md`
- 前端（React + Vite）：見 `frontend/README.md`

```powershell
cd backend; python -m pytest -q; cd ..     # 需要先 docker compose up -d --wait postgres；約 6 分鐘
cd frontend; npm test; cd ..               # 不需要資料庫
```

## 目錄

| 路徑 | 內容 |
|---|---|
| `backend/` | API、資料庫遷移、指令列（建帳號、示範資料）、測試 |
| `frontend/` | 畫面 |
| `docker/` | PostgreSQL 第一次啟動時建立 app 帳號與資料庫的 script |
| `docs/superpowers/` | 設計文件（specs）與實作計畫（plans） |
| `prototype/` | 外觀原型（一次性，只當參考） |
| `legacy/` | 舊版 Streamlit + text2sql，不維護、不跑測試；之後做問答時可以回來參考 |

## 已知限制

- 稽核紀錄「只能新增」目前靠資料庫權限，應用程式的資料庫帳號自己仍能把權限加回來，要另一個擁有者角色才會真的鎖死。
- 登入失敗 5 次會鎖帳號 15 分鐘，目前沒有解鎖指令。
- 問答（text2sql）還沒做，畫面右側只有面板外殼。
