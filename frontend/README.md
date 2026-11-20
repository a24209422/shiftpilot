# 前端（React + Vite + TypeScript）

請假排班系統的畫面。外觀來源是 `prototype/home-layout.indie-sleaze.chat-panel.prototype.html`（一次性原型，只當參考）。設計見 `docs/superpowers/specs/2026-11-20-erp-frontend-design.md`。

指令都在 **`frontend/` 目錄**執行。需要 Node 24。

```powershell
npm install
npm run dev         # 開發：http://127.0.0.1:5173，/api 會轉到 127.0.0.1:8000 的後端
npm run build       # 建置到 frontend/dist；後端偵測到就會在同一個網址（http://127.0.0.1:8000/）提供畫面
npm test            # Vitest（不需要後端與資料庫，API 是測試用的假路由）
npm run typecheck
```

開發時要同時開後端（見 `backend/README.md`）。

## 結構

```
src/
  api/        client.ts（帶 X-App-Client、解析統一錯誤格式、登入過期通知）、types.ts（跟後端回應對齊）
  auth/       登入、登出、權限（權限來自 /api/modules 的聯集；只決定顯示什麼，真正的檢查在後端）
  shell/      側邊欄、詳情面板（drawer）、表格、提示訊息；詳情面板的狀態放網址（?id=3、?id=3&edit=1、?new=1）
  forms/      表單欄位、useSubmit（防連點、欄位錯誤）、時間格式（全部用本地時間，不經過 UTC）
  home/       首頁
  modules/    每個後端模組一個資料夾，裡面是頁面與 index.ts 登記
  styles/     global.css（從原型搬來的樣式）
```

## 新增一個模組的頁面

1. 在 `src/modules/<名稱>/` 寫頁面，並在 `index.ts` 匯出一筆 `ModuleRegistration`（路徑、名稱、圖示、需要的權限、順序）。
2. 把它加進 `src/modules/index.ts` 的 `allRegistrations`。

導覽列與首頁方塊會自己長出來；沒有權限的人看不到，直接輸入網址會看到「沒有權限看這個頁面」。

## 注意

- 時間字串是不帶時區的本地時間，用 `src/forms/time.ts` 處理，不要用 `toISOString()`。
- 右側的問答面板（`src/shell/SidePanel.tsx`）目前只有外殼：可以收合、拖曳寬度，內容寫「問答尚未開放」。問答做好後把功能接進這個元件。
- `src/actionCoverage.test.tsx` 是「每個後端寫入動作都有畫面入口」的自動核對；新增寫入動作時要一起更新。
