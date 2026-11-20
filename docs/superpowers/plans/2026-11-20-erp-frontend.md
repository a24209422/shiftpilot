# 前端（階段 2）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把原型 HTML 的外觀做成 React 前端，接上已完成的後端，每個後端寫入動作都有畫面入口；建置後由 FastAPI 在同一個網址提供。

**Architecture:** `frontend/` 是 Vite + React + TypeScript 專案；一個小的 API 客戶端（帶 CSRF 標頭、解析統一錯誤格式）、TanStack Query 管讀取與快取、React Router 管頁面。外殼（側邊欄、詳情面板、提示訊息）與頁面分開，頁面由 `src/modules/<名稱>/index.ts` 登記，導覽列與首頁方塊從登記產生、用 `/api/modules` 回傳的權限篩選。後端 `createApp` 多一個選用參數 `frontendDir`，有建置結果時提供畫面與 SPA fallback。

**Tech Stack:** Node 24、npm 11、Vite、React、TypeScript、React Router（`react-router` 套件）、TanStack Query v5、Vitest、Testing Library、jsdom、`@fontsource-variable/oswald`、`@fontsource/special-elite`；後端 FastAPI（既有）。

**Spec:** `docs/superpowers/specs/2026-11-20-erp-frontend-design.md`（補充）與 `docs/superpowers/specs/2026-11-20-erp-platform-design.md`（主設計，「前端」一節與權限表）。外觀來源：`prototype/home-layout.indie-sleaze.chat-panel.prototype.html`。

## Global Constraints

- 縮排 2 個空白；變數與函式 camelCase；React 元件與型別 PascalCase；註解用正體中文，只寫「為什麼」。
- 畫面文字用正體中文（台灣用語）；原型的英文大標（`No double bookings.`、`Events.`、`Next up` 這類）照原型保留。
- 所有非 GET 請求帶標頭 `X-App-Client: web`；請求一律 `credentials: "same-origin"`。
- 時間都是不帶時區的本地時間字串。送出用 `YYYY-MM-DDTHH:mm`（`<input type="datetime-local">` 的值），後端回傳 `YYYY-MM-DDTHH:mm:ss`；日期 `YYYY-MM-DD`。不要用 `toISOString()`（會轉成 UTC）。
- 不得出現假資料、「DEMO DATA」標籤、「模擬新增模組」按鈕、請假頁、聊天面板、沒有後端的按鈕。
- 不用 `dangerouslySetInnerHTML`（使用者輸入的標題、備註會顯示在畫面上）。
- 字體打包進前端，不連 Google Fonts。
- 沒權限的按鈕不顯示；後端照樣擋。
- 開發伺服器與後端都只綁 `127.0.0.1`。
- `frontend/node_modules/`、`frontend/dist/` 不進 git；`package-lock.json` 進 git。
- 後端測試：`cd backend && python -m pytest -q`；前端測試：`cd frontend && npm test`（`vitest run`）；型別檢查：`cd frontend && npm run typecheck`（`tsc --noEmit`）。

## Review Focus

1. **用到一半 session 失效**（12 小時到期、在別的分頁改了密碼、帳號被停用）：任何請求回 401 `UNAUTHENTICATED` 都要回到登入頁並顯示「登入已過期，請重新登入」，不是空白頁或一直轉圈。登入請求本身的 401（`INVALID_CREDENTIALS`）不能被當成過期。→ Task 3、Task 4 的測試。
2. **連點送出**：表單送出中要停用按鈕，否則連點兩下會建立兩筆排程或兩個帳號。→ Task 6 的測試。
3. **寫入後畫面沒更新**：編輯、停用、取消後，列表、詳情面板、首頁摘要都要重新讀取；取消後在「不含已取消」的列表裡消失時，詳情面板要關掉而不是顯示舊資料。→ Task 7、Task 10 的測試。
4. **跨日與跨週的排程**：週日 22:00 到週一 06:00 的排程在兩週的列表都要出現，日期欄要顯示兩個日期；週的計算用本地時間，週一開始。→ Task 10 的測試。
5. **沒有對應員工的管理員建排程**：後端要求指定主辦人（`ORGANIZER_REQUIRED`）。表單在使用者沒有 `employeeId` 時要把「主辦人」設成必填並預設空白；有 `employeeId` 時預設自己。→ Task 10 的測試。

---

## API 回應格式（從真的後端傾印，前端型別照這個寫）

```ts
// GET /api/auth/me、POST /api/auth/login → { user: CurrentUser }
type Role = "employee" | "manager" | "hr" | "admin";
interface CurrentUser { id: number; email: string; role: Role; employeeId: number | null; employeeName: string | null }
// GET /api/modules
interface VisibleModule { name: string; title: string; permissions: string[] }
// 錯誤：{ error: { code: string; message: string; details: unknown } }
//   VALIDATION 的 details 可能是 { fields: { loc: (string|number)[]; message: string }[] }（請求格式錯）、{ field: string }，或 null
//   RESOURCE_CONFLICT details: { conflicts: { bookingId; title; startAt; endAt; resourceId; resourceName }[] }
//   PARTICIPANT_CONFLICT details: { conflicts: { employeeId; name; bookingId?; title?; startAt?; endAt?; reason: string }[] }
interface Resource { id: number; name: string; kind: "room" | "equipment" | "vehicle"; location: string | null; capacity: number | null; features: string[]; isActive: boolean; note: string | null }
interface Booking {
  id: number; title: string; category: string; startAt: string; endAt: string; status: "confirmed" | "cancelled";
  note: string | null; createdBy: number; createdAt: string;
  resources: { id: number; name: string; kind: Resource["kind"] }[];
  participants: { employeeId: number; name: string; role: "organizer" | "attendee" }[];
}
interface BookingSummary {
  todayBookings: Booking[]; nextBooking: Booking | null;
  resourceStatus: { resourceId: number; name: string; kind: Resource["kind"]; currentBooking: Booking | null }[];
  bookingCount: number;  // 還沒結束的已確認排程數
  resourceCount: number;
}
interface Department { id: number; name: string; parentId: number | null }
interface Employee { id: number; employeeNo: string; name: string; email: string | null; departmentId: number; jobTitle: string; managerId: number | null; hiredOn: string; isActive: boolean; leftOn: string | null }
interface CalendarDay { day: string; kind: "holiday" | "makeup_workday"; name: string }
interface User { id: number; email: string; role: Role; employeeId: number | null; employeeName: string | null; isActive: boolean; lastLoginAt: string | null; lockedUntil: string | null; createdAt: string }
interface AuditEntry { id: number; at: string; userId: number | null; module: string; action: string; entity: string; entityId: string; before: unknown; after: unknown }
```

請求欄位（camelCase）：見 `backend/app/modules/*/router.py` 的 pydantic 模型。PATCH 只送有改的欄位；明確送 `null` 代表清空。`GET /api/booking/bookings` 需要 `from`、`to`，選填 `includeCancelled=true`；`GET /api/org/calendarDays` 需要 `from`、`to`（日期）；`GET /api/core/audit` 選填 `module`、`limit`（1–500，預設 100）、`beforeId`；`GET /api/booking/resources`、`/api/org/employees` 選填 `includeInactive=true`。成功的 `logout`、`password`、`users/{id}/password`、`DELETE calendarDays` 回 204 沒有內容。

權限名稱：`org.read`、`org.manage`、`booking.read`、`booking.write`、`booking.writeAny`、`booking.resources.manage`、`core.users.manage`、`core.audit.read`。前端的「我有哪些權限」= `/api/modules` 每一筆 `permissions` 的聯集。

---

### Task 1: 後端提供建置好的前端；原型與忽略規則進 git

**Files:**
- Modify: `backend/app/main.py`
- Modify: `.gitignore`（加 `frontend/node_modules/`、`frontend/dist/`）
- Add to git: `prototype/`（三個檔案原樣）
- Test: `backend/tests/test_frontend_serving.py`

**Interfaces:**
- Produces: `createApp(databaseUrl: str, sessionHours: int = 12, frontendDir: Path | None = None) -> FastAPI`。`frontendDir` 為 `None` 或其中沒有 `index.html` 時，行為跟現在一樣（只有 API）。
- Produces: `defaultFrontendDir: Path`（`backend/app/main.py`，= repo 根目錄 `/frontend/dist`）；`createAppFromEnv()` 傳入它。

- [ ] **Step 1: 寫失敗的測試** `backend/tests/test_frontend_serving.py`，用 `tmp_path` 建一個假的 dist：`index.html`（內容 `<div id="root"></div>`）、`assets/app.js`（內容 `console.log(1)`）、`favicon.svg`。fixture `servedClient(migratedUrl, tmp_path)` 回傳 `TestClient(createApp(migratedUrl, frontendDir=dist))`。
  - `testRootServesIndexHtml`：`GET /` → 200、`text/html`、內容含 `id="root"`。
  - `testClientRoutesFallBackToIndexHtml`：`GET /bookings`、`GET /users/3` → 200 且是 `index.html` 的內容。
  - `testAssetsAreServed`：`GET /assets/app.js` → 200、內容 `console.log(1)`；`GET /favicon.svg` → 200。
  - `testUnknownApiPathStaysJson404`：`GET /api/nope` → 404、`application/json`、`error.code == "NOT_FOUND"`。
  - `testApiStillWorks`：`GET /api/auth/me` → 401 `UNAUTHENTICATED`（不是 index.html）。
  - `testPathTraversalDoesNotEscapeDist`：在 `tmp_path` 放 `secret.txt`（dist 的上一層），`GET /..%2fsecret.txt` 與 `GET /assets/..%2f..%2fsecret.txt` 的回應內容都不含 secret 的內容。
  - `testWithoutBuildOnlyApi`：`createApp(migratedUrl, frontendDir=tmp_path / "missing")` → `GET /` 回 404 JSON。
- [ ] **Step 2: 確認失敗** — `cd backend && python -m pytest tests/test_frontend_serving.py -q`。預期：`TypeError: createApp() got an unexpected keyword argument 'frontendDir'`。
- [ ] **Step 3: 實作** — 在 `createApp` 最後（所有 API 路由之後）：`dist/index.html` 存在時，掛 `/assets`（`StaticFiles`），再加一個 `@app.get("/{fullPath:path}", include_in_schema=False)`：`fullPath` 是 `api` 或以 `api/` 開頭 → 丟 `AppError("NOT_FOUND", "找不到這個 API", 404)`；`(dist / fullPath).resolve()` 在 `dist.resolve()` 底下且是檔案 → `FileResponse`；其他 → `FileResponse(dist / "index.html")`。
- [ ] **Step 4: 確認通過** — `cd backend && python -m pytest -q`。預期：全部通過（原本 226 個加上新的 7 個）。
- [ ] **Step 5: Commit** — `git add .gitignore prototype backend/app/main.py backend/tests/test_frontend_serving.py && git commit -m "後端提供建置好的前端；原型放進 repo 當參考"`

---

### Task 2: 前端專案骨架與全域樣式

**Files:**
- Create: `frontend/package.json`、`frontend/tsconfig.json`、`frontend/vite.config.ts`、`frontend/index.html`、`frontend/src/main.tsx`、`frontend/src/App.tsx`、`frontend/src/styles/global.css`、`frontend/src/test/setup.ts`、`frontend/src/vite-env.d.ts`
- Test: `frontend/src/App.test.tsx`

**Interfaces:**
- Produces: npm scripts `dev`（`vite`）、`build`（`tsc --noEmit && vite build`）、`test`（`vitest run`）、`typecheck`（`tsc --noEmit`）。
- Produces: `src/styles/global.css`：原型 `<style>` 的內容，**拿掉**聊天面板（`.chat*`、`.resizer`、`.msg`、`.bubble`、`.chips`、`.chip`、`.sql*`、`.fab`、`.thinking`、`@keyframes blink`）與 `.protoTag`；`.app` 的 grid 改成 `224px minmax(0, 1fr) auto`，第三欄是空的 `<aside className="sidePanelSlot">`（寬度 0，留給之後的問答）。新增表單用的最少樣式：`.form`、`.field`、`.field label`、`.field input/select/textarea`（沿用 `.toolbar input` 的邊框與底色）、`.fieldError`（`--error` 色、`--font-accent` 12px）、`.formError`（左邊 5px `--error` 邊線）、`.checkList`（多選清單，可捲動、最高 200px）、`.loginWrap`（置中卡片）。
- Produces: `App`（暫時只渲染外殼佔位，Task 4、5 會改）。

- [ ] **Step 1: 建立專案** — 在 `frontend/` 手寫 `package.json`（`"type": "module"`、`"private": true`），執行 `npm install react react-dom react-router @tanstack/react-query @fontsource-variable/oswald @fontsource/special-elite` 與 `npm install -D vite @vitejs/plugin-react typescript @types/react @types/react-dom vitest jsdom @testing-library/react @testing-library/user-event @testing-library/jest-dom`。`vite.config.ts`：`server: { host: "127.0.0.1", port: 5173, proxy: { "/api": "http://127.0.0.1:8000" } }`、`test: { environment: "jsdom", setupFiles: "./src/test/setup.ts", globals: true }`。`tsconfig.json`：`strict: true`、`jsx: "react-jsx"`、`moduleResolution: "bundler"`、`types: ["vitest/globals", "@testing-library/jest-dom"]`。`main.tsx` 匯入兩個字體套件與 `global.css`；CSS 的 `--font-display` 改成 `"Oswald Variable"` 開頭。
- [ ] **Step 2: 寫失敗的測試** `src/App.test.tsx`：`testAppRendersShellRegions` —— `render(<App />)` 後 `document.querySelector(".app")` 存在，且畫面上**沒有** `DEMO`、`Ask the desk` 字樣。
- [ ] **Step 3: 確認失敗** — `cd frontend && npm test`。預期：找不到 `./App` 或斷言失敗。
- [ ] **Step 4: 實作** `App.tsx` 與 `global.css`。
- [ ] **Step 5: 確認通過** — `npm test` 通過；`npm run typecheck` 沒有錯誤；`npm run build` 產生 `frontend/dist/index.html`。
- [ ] **Step 6: Commit** — `git add frontend && git commit -m "前端骨架：Vite、React、全域樣式"`（確認 `node_modules`、`dist` 沒被加入）。

---

### Task 3: API 客戶端與型別

**Files:**
- Create: `frontend/src/api/client.ts`、`frontend/src/api/types.ts`、`frontend/src/test/mockApi.ts`
- Test: `frontend/src/api/client.test.ts`

**Interfaces:**
- Produces（`types.ts`）：上面「API 回應格式」的全部型別，原樣匯出。
- Produces（`client.ts`）：
  - `class ApiError extends Error { status: number; code: string; details: unknown }`（`message` = 後端的 `error.message`）。
  - `apiGet<T>(path: string, params?: Record<string, string | number | boolean | undefined>): Promise<T>`（`undefined` 的參數不送）。
  - `apiSend<T>(method: "POST" | "PATCH" | "PUT" | "DELETE", path: string, body?: unknown): Promise<T>`；204 回 `undefined`。
  - `onSessionExpired(listener: () => void): () => void`：任何**不是** `/api/auth/login` 的請求收到 401 且 `code === "UNAUTHENTICATED"` 時呼叫。
  - 回應不是 JSON（例如後端沒開、proxy 回 502 HTML）→ `ApiError(status, "NETWORK", "連不上伺服器，請確認後端有在執行")`；`fetch` 本身丟錯也一樣。
- Produces（`test/mockApi.ts`，只給測試用）：`mockApi(routes: Record<string, (request: { body: unknown; params: URLSearchParams }) => { status?: number; body?: unknown }>)`，key 是 `"GET /api/booking/resources"` 這種格式（不含查詢字串）；替換 `globalThis.fetch`，回傳 `{ calls: { method: string; path: string; params: URLSearchParams; body: unknown; headers: Headers }[] }`；沒登記的路由回 404 並讓測試失敗。`afterEach` 還原。

- [ ] **Step 1: 寫失敗的測試** `client.test.ts`：
  - `testSendAddsCsrfHeaderAndJson`：`apiSend("POST", "/api/booking/resources", { name: "A" })` 的請求有 `X-App-Client: web`、`Content-Type: application/json`，body 是 `{"name":"A"}`。
  - `testGetHasNoBodyAndSerializesParams`：`apiGet("/api/booking/bookings", { from: "2026-11-16T00:00", to: "2026-11-23T00:00", includeCancelled: undefined })` 的查詢字串只有 `from`、`to`。
  - `testErrorBodyBecomesApiError`：409 `RESOURCE_CONFLICT` → `ApiError`，`status 409`、`code`、`message`、`details.conflicts` 都對。
  - `testNoContentReturnsUndefined`：204 → `undefined`。
  - `testSessionExpiredFiresOnUnauthenticated`：`GET /api/auth/me` 回 401 `UNAUTHENTICATED` → listener 被呼叫一次。
  - `testLoginFailureDoesNotFireSessionExpired`：`POST /api/auth/login` 回 401 `INVALID_CREDENTIALS` → listener 沒被呼叫，`ApiError.code === "INVALID_CREDENTIALS"`。
  - `testNonJsonResponseIsNetworkError`：回 502、`text/html` → `code === "NETWORK"`。
- [ ] **Step 2: 確認失敗** — `npm test -- src/api`。預期：找不到模組。
- [ ] **Step 3: 實作** `types.ts`、`client.ts`、`mockApi.ts`。
- [ ] **Step 4: 確認通過** — `npm test` 全過、`npm run typecheck` 無錯。
- [ ] **Step 5: Commit** — `git commit -m "前端 API 客戶端：CSRF 標頭、統一錯誤、session 過期通知"`

---

### Task 4: 登入、登出、session 過期、權限

**Files:**
- Create: `frontend/src/auth/AuthProvider.tsx`、`frontend/src/auth/LoginPage.tsx`、`frontend/src/auth/RequireAuth.tsx`、`frontend/src/test/renderApp.tsx`
- Modify: `frontend/src/App.tsx`（`QueryClientProvider`、`BrowserRouter`、`AuthProvider`；`/login` 是登入頁，其他路由包在 `RequireAuth` 裡）
- Test: `frontend/src/auth/auth.test.tsx`

**Interfaces:**
- Produces: `useAuth(): { user: CurrentUser | null; status: "loading" | "signedIn" | "signedOut"; notice: string | null; login(email: string, password: string): Promise<void>; logout(): Promise<void> }`。啟動時呼叫 `GET /api/auth/me`：200 → `signedIn`；401 → `signedOut`（不顯示 notice）。`onSessionExpired` 觸發 → 清掉 query 快取、`signedOut`、`notice = "登入已過期，請重新登入"`。`logout()` 呼叫 API 後 `signedOut`、清快取。
- Produces: `usePermissions(): { can(permission: string): boolean; modules: VisibleModule[]; isLoading: boolean }`，讀 `GET /api/modules`（query key `["modules"]`），只在 `signedIn` 時啟用。
- Produces: `RequireAuth`：`loading` 顯示「載入中…」；`signedOut` 導到 `/login`（記住原本路徑，登入後回去）。
- Produces（測試用）：`renderApp(options: { route?: string; user?: CurrentUser | null; permissions?: string[]; routes?: Parameters<typeof mockApi>[0] })`：自動登記 `GET /api/auth/me`（`user` 為 `null` 時回 401）與 `GET /api/modules`（把 `permissions` 放進單一模組回傳），再渲染整個 `App`（用 `MemoryRouter` 取代 `BrowserRouter`：`App` 接受選用的 `router` 參數或拆出 `AppRoutes`）。每個測試用新的 `QueryClient`（`retry: false`）。
- `LoginPage`：email、密碼、「登入」按鈕；錯誤訊息依 `code`：`INVALID_CREDENTIALS` →「帳號或密碼錯誤」；`TOO_MANY_ATTEMPTS` → 後端的 message（含鎖定時間）；`NETWORK` → 連不上伺服器；其他 → 後端 message。送出中按鈕停用。外觀用原型的黑底側欄配色與巨大窄體標題（`Schedule Desk`）。

- [ ] **Step 1: 寫失敗的測試** `auth.test.tsx`：
  - `testSignedOutUserSeesLoginPage`：`renderApp({ route: "/bookings", user: null })` → 看到「登入」按鈕。
  - `testLoginShowsShellAndReturnsToRequestedPage`：登入表單送出 → `POST /api/auth/login` 收到 `{ email, password }`；之後網址是 `/bookings`。
  - `testWrongPasswordShowsMessage`：login 回 401 `INVALID_CREDENTIALS` → 畫面出現「帳號或密碼錯誤」，仍在登入頁。
  - `testLockedAccountShowsServerMessage`：login 回 429 `TOO_MANY_ATTEMPTS`、message「嘗試太多次，請 15 分鐘後再試」→ 畫面出現這段字。
  - `testSessionExpiryReturnsToLoginWithNotice`：已登入，之後某個 API 回 401 `UNAUTHENTICATED` → 回到登入頁並顯示「登入已過期，請重新登入」。
  - `testLogoutReturnsToLogin`：按「登出」→ `POST /api/auth/logout` 被呼叫、回到登入頁、沒有 notice。（「登出」按鈕在 Task 5 的側邊欄；這個測試在 Task 5 才會通過的話，先標 `it.todo`，Task 5 補上。）
  - `testPermissionsComeFromModules`：`usePermissions().can("booking.write")` 在 permissions 含它時為真、`can("core.users.manage")` 為假。
- [ ] **Step 2: 確認失敗** — `npm test -- src/auth`。
- [ ] **Step 3: 實作** 上述檔案。
- [ ] **Step 4: 確認通過** — `npm test`、`npm run typecheck`。
- [ ] **Step 5: Commit** — `git commit -m "前端登入、登出、session 過期與權限"`

---

### Task 5: 外殼、模組登記、改密碼

**Files:**
- Create: `frontend/src/shell/Shell.tsx`、`frontend/src/shell/Sidebar.tsx`、`frontend/src/shell/Drawer.tsx`、`frontend/src/shell/Toast.tsx`、`frontend/src/shell/PageHead.tsx`、`frontend/src/shell/DataTable.tsx`、`frontend/src/shell/icons.tsx`、`frontend/src/shell/useDrawerParams.ts`、`frontend/src/shell/ChangePasswordForm.tsx`、`frontend/src/modules/registry.ts`、`frontend/src/modules/index.ts`、`frontend/src/auth/roles.ts`
- Modify: `frontend/src/App.tsx`（登入後的路由從登記產生，外面包 `Shell`）、`frontend/src/auth/AuthProvider.tsx`（加 `signOutWithNotice`）
- Test: `frontend/src/shell/shell.test.tsx`、`frontend/src/modules/registry.test.ts`

**Interfaces:**
- Produces（`registry.ts`）：
  ```ts
  interface PageRegistration { key: string; path: string; name: string; en: string; icon: IconName; requires: string; element: React.ReactNode; order: number }
  interface ModuleRegistration { backendModule: string; pages: PageRegistration[] }
  function visiblePages(registrations: ModuleRegistration[], can: (permission: string) => boolean): PageRegistration[]  // 依 order 排序；requires 沒有的頁面拿掉
  ```
  `modules/index.ts` 匯出 `allRegistrations: ModuleRegistration[]`（Task 7–12 各自加一筆；這個 task 先是空陣列）。首頁不在登記裡，固定是 `/`。
- Produces（`icons.tsx`）：`Icon({ name, size })`，路徑照原型 `iconPaths`（拿掉 `chat`、`send`、`leave`、`out`），再加 `calendar`（`events` 的變形即可）、`building`（部門）、`key`（帳號）、`log`（稽核）；`IconName` 是這些名稱的聯集型別。
- Produces（`auth/roles.ts`）：`roleLabels: Record<Role, string> = { employee: "員工", manager: "主管", hr: "人資", admin: "管理員" }`。
- Produces（`Sidebar`）：品牌 `Schedule Desk`、日期戳記（照原型 `dd.mm.yy DAY`）、首頁加 `visiblePages` 的導覽項目（`NavLink`，目前頁面 `.active`）、底部 `.sidebarFoot`：目前登入者（`employeeName ?? email` 與角色中文：員工／主管／人資／管理員）、「改密碼」、「登出」兩個 `.ghostBtn`。
- Produces（`useDrawerParams`）：詳情面板狀態放在網址查詢字串，重新整理不會丟：`{ selectedId: string | null; mode: "view" | "edit" | "new" | null; openView(id); openEdit(id); openNew(); close() }`，對應 `?id=3`、`?id=3&edit=1`、`?new=1`。`id` 用字串，因為行事曆用日期當 id。
- Produces（`Drawer`）：`Drawer({ open, title, onClose, children, footer })`，原型的 `.drawer`／`.drawerHead`／`.drawerFoot`；Esc 關閉。
- Produces（`DataTable<T>`）：`DataTable({ columns: { label: string; render(row: T): React.ReactNode; text(row: T): string }[]; rows: T[]; rowKey(row: T): string; selectedKey: string | null; onSelect(row: T): void; filterPlaceholder: string; emptyText?: string })`：原型的篩選輸入框（比對每欄 `text()`）、表格、選取列 `.selected`。
- Produces（`PageHead`）：`PageHead({ headline, sub, action?: React.ReactNode })`。
- Produces（`Toast`）：`useToast(): (message: string) => void`，3.2 秒後消失（原型的時間）。
- Produces（`ChangePasswordForm`）：側邊欄「改密碼」開一個 `Drawer`：目前密碼、新密碼、再輸入一次；兩次不同時前端擋下並顯示「兩次輸入的新密碼不一樣」；成功（204）後後端已清掉所有 session → 回登入頁並顯示 notice「密碼已更新，請用新密碼登入」（`AuthProvider` 加 `signOutWithNotice(message: string)`）。錯誤用 Task 6 之前先直接顯示 `ApiError.message`。

- [ ] **Step 1: 寫失敗的測試**
  - `registry.test.ts` `testVisiblePagesFiltersByPermissionAndSortsByOrder`：三頁（requires `booking.read`／`core.users.manage`／`org.read`，order 3／1／2），`can` 只給 `booking.read`、`org.read` → 結果依 order 是 org、booking 兩頁。
  - `shell.test.tsx` `testSidebarShowsUserAndOnlyPermittedPages`：用測試專用的登記（兩頁，一頁需要 `core.users.manage`）與 `permissions: ["booking.read"]` → 只看到一個模組導覽項目，看得到使用者名字與「主管」之類的角色中文。（`App` 接受選用的 `registrations` 參數，預設 `allRegistrations`。）
  - `testChangePasswordMismatchIsBlockedLocally`：兩次新密碼不同 → 不送請求，顯示「兩次輸入的新密碼不一樣」。
  - `testChangePasswordSuccessSignsOut`：`POST /api/auth/password` 回 204 → 回登入頁並顯示「密碼已更新，請用新密碼登入」。
  - `testDrawerStateLivesInUrl`：`renderApp({ route: "/x?id=3" })` 的測試頁（測試專用登記，頁面用 `useDrawerParams` 顯示 `selectedId`）→ 顯示 `3`；按關閉後網址沒有 `id`。
  - 補上 Task 4 的 `testLogoutReturnsToLogin`。
- [ ] **Step 2: 確認失敗** — `npm test -- src/shell src/modules`。
- [ ] **Step 3: 實作**。
- [ ] **Step 4: 確認通過** — `npm test`、`npm run typecheck`。
- [ ] **Step 5: Commit** — `git commit -m "前端外殼：側邊欄、詳情面板、表格、模組登記、改密碼"`

---

### Task 6: 表單共用元件

**Files:**
- Create: `frontend/src/forms/fields.tsx`、`frontend/src/forms/useSubmit.ts`、`frontend/src/forms/FormError.tsx`、`frontend/src/forms/time.ts`
- Test: `frontend/src/forms/forms.test.tsx`、`frontend/src/forms/time.test.ts`

**Interfaces:**
- Produces（`fields.tsx`）：受控元件，全部有 `label`、`error?: string`、`required?`：`TextField`（`type` 可為 `text`／`email`／`password`／`number`／`date`／`datetime-local`）、`TextArea`、`SelectField({ options: { value: string; label: string }[], allowEmpty?: string })`（`allowEmpty` 是空選項的文字，例如「（無）」）、`CheckList({ options, values: string[], onChange })`（多選，用核取方塊清單）、`CheckboxField`。`label` 與輸入框用 `htmlFor`／`id` 綁定，測試才能用 `getByLabelText`。
- Produces（`useSubmit.ts`）：`useSubmit<T>(action: () => Promise<T>, options: { onSuccess(result: T): void; invalidate: QueryKey[] }): { submit(): Promise<void>; pending: boolean; error: ApiError | null; fieldErrors: Record<string, string> }`。送出中 `pending` 為真、重複呼叫 `submit` 直接忽略；成功後 `invalidateQueries` 每個 key。`fieldErrors`：`details.fields[].loc` 最後一段當欄位名；`details.field` 也對應過去。
- Produces（`FormError`）：`FormError({ error })`：顯示 `error.message`；有 `fieldErrors` 的已標在欄位旁，這裡只顯示總訊息。`RESOURCE_CONFLICT`、`PARTICIPANT_CONFLICT` 不在這裡處理（Task 10 自己畫）。
- Produces（`time.ts`）：
  - `formatDay(value: string): string` → `11/16（一）`
  - `formatTime(value: string): string` → `10:00`
  - `formatRange(startAt: string, endAt: string): string`：同一天 `11/16（一） 10:00–11:00`；跨日 `11/16（日） 22:00 – 11/17（一） 06:00`
  - `toInputValue(value: string): string`：`2026-11-16T10:00:00` → `2026-11-16T10:00`
  - `weekStart(date: Date): Date`（本地時間週一 00:00）、`addDays(date: Date, days: number): Date`、`toLocalString(date: Date): string` → `YYYY-MM-DDTHH:mm`（不經過 UTC）、`toLocalDate(date: Date): string` → `YYYY-MM-DD`
  - 解析後端字串一律自己切欄位建 `new Date(y, m - 1, d, hh, mm)`，不依賴瀏覽器怎麼解析 ISO 字串。

- [ ] **Step 1: 寫失敗的測試**
  - `time.test.ts`：`testFormatRangeSameDay`、`testFormatRangeCrossesMidnight`（`2026-11-22T22:00:00` 到 `2026-11-23T06:00:00` → `11/22（日） 22:00 – 11/23（一） 06:00`）、`testWeekStartIsLocalMonday`（`new Date(2026, 10, 22, 23, 30)` 週日 → `2026-11-16T00:00`；`new Date(2026, 10, 23, 0, 0)` 週一 → `2026-11-23T00:00`）、`testToLocalStringDoesNotShiftToUtc`。
  - `forms.test.tsx`：
    - `testDoubleSubmitSendsOnce`：一個用 `useSubmit` 的測試表單，連點兩下送出（API 延遲回應）→ `calls` 只有一筆；送出中按鈕 `disabled`。
    - `testFieldErrorsMapFromValidationDetails`：422 `details.fields = [{ loc: ["body", "name"], message: "Field required" }]` → `name` 欄位旁出現「Field required」。
    - `testServerMessageShown`：422 `VALIDATION`「資源名稱不能是空白」、`details: null` → 表單顯示這段字。
    - `testSuccessInvalidatesQueries`：成功後指定的 query 被重新讀取（`GET` 被呼叫第二次）。
- [ ] **Step 2: 確認失敗** — `npm test -- src/forms`。
- [ ] **Step 3: 實作**。
- [ ] **Step 4: 確認通過** — `npm test`、`npm run typecheck`。
- [ ] **Step 5: Commit** — `git commit -m "前端表單元件、送出狀態與時間格式"`

---

### Task 7: 資源頁

**Files:**
- Create: `frontend/src/modules/booking/ResourcesPage.tsx`、`frontend/src/modules/booking/ResourceForm.tsx`、`frontend/src/modules/booking/labels.ts`、`frontend/src/modules/booking/queries.ts`、`frontend/src/modules/booking/index.ts`
- Modify: `frontend/src/modules/index.ts`（加入 booking 登記）
- Test: `frontend/src/modules/booking/resources.test.tsx`

**Interfaces:**
- Consumes: Task 5 的 `DataTable`、`Drawer`、`PageHead`、`useDrawerParams`；Task 6 的欄位與 `useSubmit`。
- Produces（`queries.ts`）：`useResources(includeInactive = false)`，key `["resources", { includeInactive }]`。Task 10 在同一個檔案加 `useBookings`。
- Produces（`labels.ts`）：`resourceKindLabels = { room: "會議室", equipment: "設備", vehicle: "公務車" }`、`resourceKindTones = { room: "ok", equipment: "warn", vehicle: "info" }`。
- Produces（`booking/index.ts`）：`bookingRegistration: ModuleRegistration`，`backendModule: "booking"`；這個 task 先放資源頁：`{ key: "resources", path: "/resources", name: "資源", en: "Resources", icon: "resources", requires: "booking.read", order: 20 }`。Task 10 再加排程頁（order 10）。
- 頁面：`PageHead`（`Resources.`、「資源・共 N 筆。會議室、設備與公務車」；有 `booking.resources.manage` 才有「新增資源」）、勾選「含已停用」（`includeInactive`）、欄位：名稱、種類（標籤）、地點、容量、狀態（停用顯示 `.tag.mute`「已停用」）。點列開詳情：名稱、種類、地點、容量、設備特色（`features` 用「、」接）、備註、狀態；底部（有權限才顯示）「編輯」「停用」或「重新啟用」。
- 表單：名稱（必填）、種類（選單）、地點、容量（數字，空白送 `null`）、特色（以逗號或頓號分隔的文字，送出時切成陣列、去空白）、備註。新增 `POST`，編輯 `PATCH` 只送改過的欄位。停用／重新啟用 = `PATCH { isActive }`。query key `["resources", { includeInactive }]`；寫入後 invalidate `["resources"]` 與 `["summary"]`。

- [ ] **Step 1: 寫失敗的測試** `resources.test.tsx`：
  - `testListShowsResourcesWithKindLabels`：兩筆資源 → 表格有名稱與「會議室」「設備」。
  - `testEmployeeSeesNoWriteButtons`：permissions 只有 `booking.read` → 沒有「新增資源」，點列後沒有「編輯」「停用」。
  - `testAdminCreatesResource`：按「新增資源」、填名稱與種類、特色填「video, whiteboard」→ `POST` body `{ name, kind: "room", location: null, capacity: null, features: ["video", "whiteboard"], note: null }`，之後列表重新讀取。
  - `testEditSendsOnlyChangedFields`：開編輯、只改地點 → `PATCH` body 只有 `{ location }`。
  - `testDeactivateRefreshesAndShowsInactiveTag`：按「停用」→ `PATCH { isActive: false }`；勾「含已停用」後那一列顯示「已停用」。
  - `testDuplicateNameShowsServerMessage`：`POST` 回 409 `DUPLICATE`「資源名稱已存在」→ 表單顯示這段字，面板不關。
- [ ] **Step 2: 確認失敗** — `npm test -- src/modules/booking`。
- [ ] **Step 3: 實作**。
- [ ] **Step 4: 確認通過** — `npm test`、`npm run typecheck`。
- [ ] **Step 5: Commit** — `git commit -m "前端資源頁：列表、新增、編輯、停用"`

---

### Task 8: 部門與員工頁

**Files:**
- Create: `frontend/src/modules/org/DepartmentsPage.tsx`、`frontend/src/modules/org/DepartmentForm.tsx`、`frontend/src/modules/org/EmployeesPage.tsx`、`frontend/src/modules/org/EmployeeForm.tsx`、`frontend/src/modules/org/queries.ts`、`frontend/src/modules/org/index.ts`
- Modify: `frontend/src/modules/index.ts`
- Test: `frontend/src/modules/org/departments.test.tsx`、`frontend/src/modules/org/employees.test.tsx`

**Interfaces:**
- Produces（`queries.ts`）：`useDepartments()`（key `["departments"]`）、`useEmployees(includeInactive = false)`（key `["employees", { includeInactive }]`）。排程表單（Task 10）與帳號表單（Task 12）也用這兩個。
- Produces（`org/index.ts`）：`orgRegistration`，頁面：員工 `{ key: "employees", path: "/employees", name: "員工", en: "People", icon: "people", requires: "org.read", order: 30 }`、部門 `{ key: "departments", path: "/departments", name: "部門", en: "Departments", icon: "building", requires: "org.read", order: 40 }`。Task 9 加行事曆。
- 部門頁：欄位名稱、上層部門（名稱，沒有顯示「—」）、員工數（由 `useEmployees` 算）。有 `org.manage` 才有「新增部門」「編輯」。表單：名稱、上層部門（選單，排除自己；`allowEmpty="（無）"`）。`DEPARTMENT_CYCLE` 顯示後端訊息。
- 員工頁：勾「含已停用」；欄位員工編號、姓名、部門、職稱、主管、到職日、狀態（停用顯示「已離職」或「已停用」）。有 `org.manage` 才有「新增員工」「編輯」「停用」／「重新啟用」。表單：員工編號、姓名、email、部門（選單）、職稱、主管（選單，排除自己、只列在職的；`allowEmpty="（無）"`）、到職日。「停用」開一個小表單：離職日（預設今天，可空白）→ `PATCH { isActive: false, leftOn }`；「重新啟用」→ `PATCH { isActive: true, leftOn: null }`。`MANAGER_CYCLE`、`DUPLICATE` 顯示後端訊息。寫入後 invalidate `["employees"]`、`["departments"]`。

- [ ] **Step 1: 寫失敗的測試**
  - `departments.test.tsx`：`testDepartmentsListShowsParentName`、`testCreateDepartmentWithParent`（body `{ name, parentId: 1 }`）、`testParentOptionsExcludeSelf`（編輯部門 2 時，上層選單沒有部門 2）、`testCycleErrorShown`（422 `DEPARTMENT_CYCLE` → 顯示訊息）、`testEmployeeRoleSeesNoWriteButtons`。
  - `employees.test.tsx`：`testListShowsDepartmentAndManagerNames`、`testCreateEmployeeSendsDates`（`hiredOn: "2026-11-20"`、`managerId: null` 時送 `null`）、`testDeactivateSendsLeftOn`（`PATCH { isActive: false, leftOn: "2026-11-30" }`）、`testReactivateClearsLeftOn`、`testManagerOptionsExcludeSelfAndInactive`。
- [ ] **Step 2: 確認失敗** — `npm test -- src/modules/org`。
- [ ] **Step 3: 實作**。
- [ ] **Step 4: 確認通過** — `npm test`、`npm run typecheck`。
- [ ] **Step 5: Commit** — `git commit -m "前端部門與員工頁"`

---

### Task 9: 行事曆頁

**Files:**
- Create: `frontend/src/modules/org/CalendarPage.tsx`、`frontend/src/modules/org/CalendarDayForm.tsx`
- Modify: `frontend/src/modules/org/index.ts`（加 `{ key: "calendar", path: "/calendar", name: "行事曆", en: "Calendar", icon: "calendar", requires: "org.read", order: 50 }`）
- Test: `frontend/src/modules/org/calendar.test.tsx`

**Interfaces:**
- 頁面：年份切換（上一年／今年／下一年），讀 `GET /api/org/calendarDays?from=YYYY-01-01&to=YYYY-12-31`（key `["calendarDays", year]`）。欄位：日期（`formatDay` 加年份）、種類（`holiday` →「放假」`.tag.ok`；`makeup_workday` →「補班」`.tag.warn`）、名稱。有 `org.manage` 才有「新增日期」「編輯」「刪除」。詳情的 id 是日期字串。
- 表單：日期（新增時可填；編輯時唯讀，因為 PUT 以日期為鍵）、種類（選單）、名稱 → `PUT /api/org/calendarDays/{day}` body `{ kind, name }`。刪除 → `DELETE`，成功後關閉面板、invalidate `["calendarDays"]`。刪除前用面板內的確認（按「刪除」後按鈕變「確定刪除？」再按一次），不用 `window.confirm`。

- [ ] **Step 1: 寫失敗的測試** `calendar.test.tsx`：`testListsDaysOfSelectedYear`（請求的 `from`／`to` 是今年的 1/1 與 12/31；切下一年後換成下一年）、`testCreateDayUsesPut`（`PUT /api/org/calendarDays/2026-12-25` body `{ kind: "holiday", name: "行憲紀念日" }`）、`testDeleteNeedsSecondClick`（第一次按不送請求，第二次才送 `DELETE`，之後面板關閉）、`testEmployeeSeesNoWriteButtons`。
- [ ] **Step 2: 確認失敗** — `npm test -- src/modules/org/calendar`。
- [ ] **Step 3: 實作**。
- [ ] **Step 4: 確認通過** — `npm test`、`npm run typecheck`。
- [ ] **Step 5: Commit** — `git commit -m "前端行事曆頁"`

---

### Task 10: 排程頁（含衝突與「仍要排」）

**Files:**
- Create: `frontend/src/modules/booking/BookingsPage.tsx`、`frontend/src/modules/booking/BookingForm.tsx`、`frontend/src/modules/booking/ConflictNotice.tsx`
- Modify: `frontend/src/modules/booking/queries.ts`（加 `useBookings`）、`frontend/src/modules/booking/index.ts`（加 `{ key: "bookings", path: "/bookings", name: "排程", en: "Events", icon: "events", requires: "booking.read", order: 10 }`）
- Test: `frontend/src/modules/booking/bookings.test.tsx`

**Interfaces:**
- Consumes: Task 6 `time.ts`；Task 8 `useEmployees`；Task 7 的資源 query。
- Produces（`queries.ts`）：`useBookings(weekStartDate: Date, includeCancelled: boolean)`，key `["bookings", toLocalString(weekStartDate), includeCancelled]`，`from = weekStart`、`to = weekStart + 7 天`（後端回傳與這段時間**重疊**的排程，跨週的會兩週都出現）。資源選項用 Task 7 的 `useResources`。
- 頁面：週的切換放在網址 `?week=YYYY-MM-DD`（週一日期；沒有時是本週），「上一週」「本週」「下一週」三個按鈕，標題下方顯示 `11/16（一） – 11/22（日）`；勾「含已取消」。欄位：日期時間（`formatRange`）、標題、類別、資源（名稱用「、」接）、主辦人、狀態（取消的顯示 `.tag.mute`「已取消」）。有 `booking.write` 才有「新增排程」。
- 詳情：標題、時間、類別、資源、主辦人、參加者、備註、建立時間、狀態。「編輯」「取消排程」只在 `status === "confirmed"` 且（`booking.createdBy === user.id` 或 `can("booking.writeAny")`）時顯示。取消用跟行事曆一樣的二次確認 → `POST /api/booking/bookings/{id}/cancel`。
- 表單：標題、類別（文字）、開始、結束（`datetime-local`）、資源（`CheckList`，只列啟用中的；編輯時已選但已停用的也列出並標「已停用」）、主辦人（`SelectField`，在職員工；`user.employeeId` 有值時預設自己，沒有時預設空白且必填）、參加者（`CheckList`，在職員工，排除主辦人）、備註。新增時預設開始 = 下一個整點、結束 = 開始 + 1 小時。新增 `POST`；編輯 `PATCH` 只送改過的欄位（`resourceIds`、`participantEmployeeIds` 有改才送）。
- 衝突（`ConflictNotice`）：
  - `RESOURCE_CONFLICT`：標題「資源在這個時段已被預約」，逐筆列出「資源名稱：撞到的排程標題（formatRange）」。沒有「仍要排」。
  - `PARTICIPANT_CONFLICT`：標題「有參加者在這個時段不方便」，逐筆列出「姓名：reason（有 title 時加上標題與時間）」，按鈕「仍要排」→ 同一份內容加 `acknowledgeWarnings: true` 重送。
  - `ORGANIZER_REQUIRED`：標在主辦人欄位旁。
  - 其他錯誤交給 `FormError`。
- 寫入後 invalidate `["bookings"]`、`["summary"]`；如果目前選取的排程在重新讀取後不在列表裡（例如取消後列表不含已取消），關閉詳情面板。

- [ ] **Step 1: 寫失敗的測試** `bookings.test.tsx`（用 `vi.useFakeTimers({ toFake: ["Date"] })` 固定「現在」為 `2026-11-20T09:30` 本地時間）：
  - `testWeekRangeRequestedAndNavigable`：第一次請求 `from=2026-11-16T00:00&to=2026-11-23T00:00`；按「下一週」→ `from=2026-11-23T00:00`，網址有 `week=2026-11-23`。
  - `testCrossDayBookingShowsBothDates`：一筆 `2026-11-22T22:00:00`–`2026-11-23T06:00:00` → 表格顯示 `11/22（日） 22:00 – 11/23（一） 06:00`。
  - `testCreateBookingDefaultsOrganizerToSelf`：`user.employeeId = 2` → 主辦人預設是員工 2；送出的 body 有 `organizerEmployeeId: 2`、`startAt: "2026-11-20T10:00"`、`endAt: "2026-11-20T11:00"`。
  - `testAdminWithoutEmployeeMustPickOrganizer`：`user.employeeId = null` → 主辦人空白；沒選就送出時前端顯示「請選擇主辦人」且不送請求。
  - `testResourceConflictListsClashAndHasNoOverride`：`POST` 回 409 `RESOURCE_CONFLICT`（一筆「3F 大會議室」「團隊週會」）→ 顯示「3F 大會議室」與「團隊週會」，沒有「仍要排」按鈕。
  - `testParticipantWarningCanBeOverridden`：第一次 `POST` 回 409 `PARTICIPANT_CONFLICT`（「林小美」「同時段已有其他排程」）→ 顯示原因；按「仍要排」→ 第二次 `POST` 的 body 有 `acknowledgeWarnings: true`，其他欄位相同；成功後面板關閉、列表重新讀取。
  - `testEditAndCancelOnlyForCreatorOrWriteAny`：`createdBy` 是別人、permissions 沒有 `booking.writeAny` → 沒有「編輯」「取消排程」；有 `booking.writeAny` → 有。
  - `testCancelClosesDrawerWhenRowDisappears`：取消（二次確認）→ `POST …/cancel`；重新讀取的列表不含這筆 → 詳情面板關閉。
  - `testEditSendsOnlyChangedFields`：只改標題 → `PATCH` body 只有 `{ title }`。
- [ ] **Step 2: 確認失敗** — `npm test -- src/modules/booking/bookings`。
- [ ] **Step 3: 實作**。
- [ ] **Step 4: 確認通過** — `npm test`、`npm run typecheck`。
- [ ] **Step 5: Commit** — `git commit -m "前端排程頁：週列表、新增、編輯、取消、衝突與仍要排"`

---

### Task 11: 首頁

**Files:**
- Create: `frontend/src/home/HomePage.tsx`
- Modify: `frontend/src/App.tsx`（`/` 是首頁）
- Test: `frontend/src/home/home.test.tsx`

**Interfaces:**
- Consumes: `GET /api/booking/summary`（key `["summary"]`，只在 `can("booking.read")` 時讀）；`visiblePages`（方塊）。
- 版面照原型 `renderHome`：
  - `PageHead`：`No double bookings.`，副標「YYYY/MM/DD 星期X。今天 N 場排程。」，有 `booking.write` 才有「新增排程」→ 導到 `/bookings?new=1`。
  - 四個數字：「今天的排程」= `todayBookings.length`（note：下一場在今天 → `下一場 HH:mm`，否則「今天沒有下一場了」）、「會議室使用中」= `resourceStatus` 中 `kind === "room"` 且有 `currentBooking` 的數量／會議室總數（note「此刻」）、「接下來的排程」= `bookingCount`（note「還沒結束的已確認排程」）、「資源」= `resourceCount`（note「可以預約」）。
  - `All modules`：`visiblePages` 的方塊（No.01…、圖示、`en`、`name`），點了導到該頁。
  - `Next up`：照原型的 `.feature`（相機戳記是現在時間）；`nextBooking` 為 `null` 顯示「沒有接下來的排程」。按「View all events →」到 `/bookings`。
  - `Rooms right now`：`resourceStatus` 只列 `room`；使用中顯示 `currentBooking.title` 與 `.tag.warn`「使用中」，否則 `.tag.ok`「空著」。
  - `On the run sheet`：今天的排程表格（時間、標題、資源），點列導到 `/bookings?id=<id>`。
  - 原型的 `Needs a decision`（請假）**不做**。
- `BookingsPage` 要支援 `?new=1` 直接開新增表單（Task 10 的 `useDrawerParams` 已涵蓋，這裡測一次）。

- [ ] **Step 1: 寫失敗的測試** `home.test.tsx`（固定現在 `2026-11-20T09:30`）：
  - `testStatsFromSummary`：summary 有 2 筆今天、會議室 2 間其中 1 間使用中、`bookingCount: 5`、`resourceCount: 4` → 畫面有「2」「1/2」「5」「4」。
  - `testRoomsRightNowListsOnlyRooms`：`resourceStatus` 含 vehicle → 不出現在 `Rooms right now`。
  - `testNoNextBooking`：`nextBooking: null` → 「沒有接下來的排程」。
  - `testNewBookingButtonOpensForm`：按「新增排程」→ 網址 `/bookings?new=1`，畫面出現排程表單的「標題」欄位。
  - `testNoLeaveOrDemoContent`：畫面沒有「請假」「DEMO」「Needs a decision」。
- [ ] **Step 2: 確認失敗** — `npm test -- src/home`。
- [ ] **Step 3: 實作**。
- [ ] **Step 4: 確認通過** — `npm test`、`npm run typecheck`。
- [ ] **Step 5: Commit** — `git commit -m "前端首頁：今天的排程、下一場、會議室現況"`

---

### Task 12: 帳號與稽核頁（管理員）

**Files:**
- Create: `frontend/src/modules/core/UsersPage.tsx`、`frontend/src/modules/core/UserForm.tsx`、`frontend/src/modules/core/ResetPasswordForm.tsx`、`frontend/src/modules/core/AuditPage.tsx`、`frontend/src/modules/core/index.ts`
- Modify: `frontend/src/modules/index.ts`
- Test: `frontend/src/modules/core/users.test.tsx`、`frontend/src/modules/core/audit.test.tsx`

**Interfaces:**
- Produces（`core/index.ts`）：`coreRegistration`，頁面：帳號 `{ key: "users", path: "/users", name: "帳號", en: "Accounts", icon: "key", requires: "core.users.manage", order: 60 }`、稽核 `{ key: "audit", path: "/audit", name: "稽核", en: "Audit log", icon: "log", requires: "core.audit.read", order: 70 }`。
- Consumes: Task 5 的 `roleLabels`；Task 8 的 `useEmployees`。
- 帳號頁：欄位 email、角色、連結員工（`employeeName`）、最後登入（`lastLoginAt`，沒有顯示「從未」）、狀態（停用 `.tag.mute`、`lockedUntil` 晚於現在 `.tag.bad`「鎖定中」）。「新增帳號」表單：email、密碼（8–128 字，前端先擋長度並顯示「密碼要 8 到 128 字元」）、角色、連結員工（在職員工中還沒有帳號的；`allowEmpty="（不連結）"`）。詳情：「編輯」（角色、連結員工、停用勾選；`PATCH` 只送改過的）、「重設密碼」（新密碼兩次）。對自己操作時後端回 `CANNOT_MODIFY_SELF`，顯示後端訊息即可。寫入後 invalidate `["users"]`。
- 稽核頁：模組篩選（全部／org／core／booking），一次讀 100 筆（key `["audit", module]`，`useInfiniteQuery`，下一頁 `beforeId` = 這頁最後一筆的 `id`，回傳少於 100 筆就沒有下一頁），表格：時間、使用者（`userId` 對應帳號 email，查不到顯示 `#id`，`null` 顯示「系統」）、模組、動作、對象（`entity #entityId`）。點列詳情顯示 `before`、`after`（`JSON.stringify(value, null, 2)` 放在 `<pre class="mono">`）。底部「載入更多」。

- [ ] **Step 1: 寫失敗的測試**
  - `users.test.tsx`：`testListShowsRoleLabelsAndLockState`、`testCreateUserValidatesPasswordLength`（7 字 → 不送請求、顯示提示）、`testCreateUserSendsEmployeeLink`（body `{ email, password, role: "employee", employeeId: 3 }`）、`testEmployeeOptionsExcludeLinkedEmployees`、`testResetPasswordUsesPost`（`POST /api/core/users/2/password` body `{ newPassword }`）、`testCannotModifySelfMessageShown`。
  - `audit.test.tsx`：`testFirstPageThenLoadMoreUsesBeforeId`（第一頁 100 筆、最後 id 501 → 按「載入更多」請求 `beforeId=501`；第二頁 3 筆後「載入更多」消失）、`testModuleFilterSendsModule`、`testDetailShowsBeforeAndAfter`。
  - `testNonAdminCannotSeeAccountsOrAudit`（放 `users.test.tsx`）：permissions 是 hr 的那組 → 導覽沒有「帳號」「稽核」；直接開 `/users` 顯示「沒有權限看這個頁面」（路由層：頁面的 `requires` 不符時顯示這段字，`App` 統一處理）。
- [ ] **Step 2: 確認失敗** — `npm test -- src/modules/core`。
- [ ] **Step 3: 實作**（含 `App` 的無權限畫面）。
- [ ] **Step 4: 確認通過** — `npm test`、`npm run typecheck`。
- [ ] **Step 5: Commit** — `git commit -m "前端帳號與稽核頁"`

---

### Task 13: 核對入口、說明文件、實際跑一輪

**Files:**
- Create: `frontend/README.md`
- Modify: `backend/README.md`（「啟動」一節：先 `cd frontend && npm install && npm run build`，之後 `127.0.0.1:8000/` 就是畫面；開發時兩個終端機：uvicorn 與 `npm run dev`，開 `127.0.0.1:5173`）、`README.md`（根目錄的說明行補上前端位置）
- Test: `frontend/src/actionCoverage.test.tsx`

**Interfaces:**
- `actionCoverage.test.tsx` `testEveryWriteActionHasAnEntry`：以管理員權限（全部 8 個權限）、`mockApi` 提供每個列表一筆資料，逐頁打開，斷言下列按鈕文字都找得到（找不到就失敗並列出缺哪個）：登出、改密碼、新增帳號、編輯（帳號）、重設密碼、新增部門、編輯（部門）、新增員工、編輯（員工）、停用（員工）、新增日期、編輯（行事曆）、刪除（行事曆）、新增資源、編輯（資源）、停用（資源）、新增排程、編輯（排程）、取消排程。這就是設計補充「寫入動作核對表」的自動版。

- [ ] **Step 1: 寫測試並確認結果** — `npm test -- src/actionCoverage`。前面的 task 都做完的話會直接通過；有缺的話補上缺的入口（屬於哪個 task 的就照那個 task 的規格），再跑到通過。這一步的測試先寫好再跑，跑的結果要讀。
- [ ] **Step 2: 寫說明文件**（如上）。`frontend/README.md`：怎麼裝、`dev`／`build`／`test`／`typecheck`、目錄結構、怎麼新增一個模組的頁面（在 `src/modules/<名稱>/index.ts` 登記、加進 `modules/index.ts`）、`prototype/` 是外觀來源。
- [ ] **Step 3: 全部驗證** — `cd backend && python -m pytest -q`（全過）；`cd frontend && npm test && npm run typecheck && npm run build`（全過、產生 `dist/`）。
- [ ] **Step 4: 實際跑一輪** — 用暫時資料庫（不碰使用者的 `schedule` 資料）：在 `schedule_test` 建暫時 schema 或另建 `schedule_smoke`，套遷移、建管理員（用程式呼叫 `createUserCommand`，不經過互動輸入）、`seedDemo`，用 `createApp(url, frontendDir=frontend/dist)` 起 uvicorn 在 `127.0.0.1:8001`。用瀏覽器（Claude in Chrome）登入，逐項操作核對表，截圖或錄 GIF 給使用者；最後用一個 `employee` 帳號登入，確認寫入按鈕只出現在自己建立的排程上。跑完刪掉暫時資料庫。發現的問題：屬於規格內的就修（先寫會失敗的測試）；規格外的列給使用者。
- [ ] **Step 5: Commit** — `git commit -m "前端說明文件與寫入動作核對測試"`

---

## 之後（不在這份計畫）

- 階段 3 切換：Dockerfile 多階段建置（Node 建前端、Python 跑後端）、`docker compose up` 一個網址、設定 `TZ`、根目錄 README、移除 `legacy/` 以外的 Streamlit 痕跡。
- 使用者自己調整的外觀與表單細節。
