# 設計補充：切換（階段 3）

日期：2026-11-21　｜　規模：小改動（`2026-11-20-erp-platform-design.md` 的階段 3）　｜　狀態：**已核准（2026-11-21）**

## 目的

一個指令（`docker compose up -d --build`）啟動整個系統，`http://127.0.0.1:8000/` 同時提供畫面與 API；舊的 Streamlit 版本從根目錄收掉，README 改寫成新系統的說明。

## 做法比較

| 做法 | 取捨 | 結果 |
|---|---|---|
| 前端、後端各一個容器（例如前端用 nginx） | 要處理兩個網址或反向代理、CORS 或 cookie 網域 | 不採用：主設計要求同一個網址 |
| 根目錄一個多階段 `Dockerfile`：Node 建前端 → Python 跑後端並帶著 `dist` | 映像檔裡有後端與前端建置結果；後端已經會提供畫面（`createApp(frontendDir=…)`） | **採用** |

## 決定

- **`Dockerfile`（根目錄）**：第一階段 `node:24` 執行 `npm ci && npm run build`；第二階段 `python:3.13-slim` 安裝 `backend/requirements.txt`，複製 `backend/` 與前端的 `dist` 到映像檔裡，`createAppFromEnv` 的 `defaultFrontendDir` 要指得到那個位置。容器內不用 root 執行。
- **`docker-compose.yml` 加 `app` 服務**：
  - `build: .`，`depends_on: postgres（service_healthy）`，`restart: unless-stopped`
  - 只綁 `127.0.0.1:8000:8000`（容器內 uvicorn 聽 `0.0.0.0`，對外仍只有本機）
  - `TZ=Asia/Taipei`；`DATABASE_URL` 指向 compose 內部的 `postgres:5432`，密碼從 `.env` 的 `APP_DB_PASSWORD` 帶入
  - 啟動時先 `python -m app.cli migrate`，成功才啟動 uvicorn（失敗就讓容器停下，不用舊結構跑）
- **建第一個管理員**：`docker compose exec app python -m app.cli createUser --email … --role admin`（互動輸入密碼）；示範資料同理用 `seedDemo`。
- **舊檔案搬到 `legacy/`，不刪除**：根目錄 `requirements.txt` → `legacy/requirements.txt`；根目錄 `README.md` → `legacy/README.md`（評測紀錄留著）。
- **根目錄 `README.md` 改寫**：系統是什麼、一個指令啟動、建管理員、本機開發（後端、前端各自的 README）、跑測試、目錄結構、`legacy/` 是什麼。
- **`.dockerignore` 改寫**：排除 `.env`、`.git`、`legacy/`、`prototype/`、`docs/`、`frontend/node_modules`、`frontend/dist`、`backend/tests`、快取。
- **資料庫沿用同一個 volume**：使用者已建立的帳號與資料保留。
- **衝突提醒**：容器與手動啟動的 uvicorn 都用 8000，同時只能跑一個（寫進 README）。

## 非目標

- 稽核表「只能新增」的強化（另一個擁有者角色）：留在延後清單
- HTTPS、對區網開放
- 正式環境的備份、監控

## 怎麼驗證

- 用另一個 compose 專案名稱與不同的 port 從空的 volume 跑一次（不動使用者現在的資料）：`docker compose -p schedule-verify up -d --build` 之類，確認容器健康、`/` 回畫面、`migrate` 自動套用、`createUser` 能用、登入後能建員工、建資源、建排程、撞期會被擋。跑完 `down -v` 清掉。
- 後端與前端的既有測試照常全過。
