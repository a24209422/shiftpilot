# 前端（React + Vite + TypeScript）

ShiftPilot 的畫面。外觀來源是 `prototype/home-layout.indie-sleaze.chat-panel.prototype.html`（一次性原型，只當參考）。設計見 `docs/superpowers/specs/2026-11-20-erp-frontend-design.md`。

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
  timeline/   時間軸頁與時間計算；資料由各模組登記的檢視、來源提供
  modules/    每個後端模組一個資料夾，裡面是頁面與 index.ts 登記
    leave/     請假頁、假別與額度頁；時間軸的請假來源
    shift/     班表頁（一週表格、單日調整、週班表）、班別頁；時間軸的上班底色
  styles/     global.css（從原型搬來的樣式）
```

## 新增一個模組的頁面

1. 在 `src/modules/<名稱>/` 寫頁面，並在 `index.ts` 匯出一筆 `ModuleRegistration`（路徑、名稱、圖示、需要的權限、順序）。
2. 把它加進 `src/modules/index.ts` 的 `allRegistrations`。

導覽列與首頁方塊會自己長出來；沒有權限的人看不到，直接輸入網址會看到「沒有權限看這個頁面」。

## 讓模組的資料出現在時間軸

在模組的 `ModuleRegistration` 加 `timelineSources`（提供長條）；如果模組擁有一種新的「列」（例如員工），再加 `timelineViews`。型別在 `src/timeline/types.ts`，範例是 `src/modules/booking/timeline.ts`。查詢的 `queryKey` 要放在模組既有的前綴底下（例如 `["bookings", …]`），寫入後現有的 invalidate 才會順便更新時間軸。設計見 `docs/superpowers/specs/2026-11-20-timeline-design.md`。項目有三種畫法：`event`（長條，例如會議）、`block`（區塊，例如請假）、`status`（整列底色，例如上班時段，畫在最底層、不能點、不佔用點空檔新增的時段）；沒有 `link` 的項目畫成不能點的區塊。時間軸頁有多種看得到的檢視時，上方會出現檢視分頁（網址參數 `view`）。

## 注意

- 時間字串是不帶時區的本地時間，用 `src/forms/time.ts` 處理，不要用 `toISOString()`。
- 右側的問答面板（`src/shell/SidePanel.tsx`）目前只有外殼：可以收合、拖曳寬度，內容寫「問答尚未開放」。問答做好後把功能接進這個元件。
- `src/actionCoverage.test.tsx` 是「每個後端寫入動作都有畫面入口」的自動核對；新增寫入動作時要一起更新。
