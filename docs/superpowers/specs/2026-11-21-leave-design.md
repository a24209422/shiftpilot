# 設計：請假模組

日期：2026-11-21　｜　規模：子專案（平台設計的第 2 塊）　｜　狀態：**待審閱**

前一份：`2026-11-20-erp-platform-design.md`（子專案順序第 2 項）、`2026-11-20-timeline-design.md`（「之後怎麼擴充」一節）。時間軸設計「不做」裡的**人員檢視**與 `event` 以外的畫法（占用），**由這份解除**其中的「員工檢視」與 `block` 種類。

## 目的

讓員工在系統裡請假、主管核准、人資管理假別與額度。請假會自動出現在排會議的參加者警告裡，也會畫在時間軸上，讓「誰哪天不在」一眼看得到。

這也是第一個「接上」平台既有接口的模組：「不可用」提供者、時間軸的檢視與來源登記、`listSubordinateIds` 這一類組織查詢。做完可以驗證「新增模組不用改舊模組」是否成立（時間軸新增一種畫法除外，見下文）。

## 範圍

**做**

- 後端模組 `leave`：假別、請假申請、額度調整三張表；特休依年資計算（週年制）；年度上限檢查；直屬主管核准；未休特休報表
- 「不可用」提供者：待核准、已核准的假出現在排會議的參加者警告
- 前端「請假」頁、「假別與額度」頁、首頁「待審核請假」方塊
- 時間軸：組織模組登記「員工」檢視；時間軸新增 `block` 種類；請假模組登記「請假」來源（**最後一個任務**）
- 稽核頁的模組篩選加上 `leave`

**不做**

- 婚、喪、產假等「依事件」的條件（親屬關係、結婚日、預產期）：由主管核准時判斷
- 生理假「每月 1 天」等按月的規則：當作一般的年度上限
- 特休曆年制、未休特休遞延、折算工資（沒有薪資模組，只提供未休報表）
- 人資代別人申請、代理人、多關核准、email 通知
- 依班表算時數：排班模組做好之前用固定上班時間
- 半小時以下的單位：最小單位 1 小時
- 會議出現在員工檢視上：員工檢視第一版只有請假來源
- 示範用的請假資料

## 做法比較

**額度與餘額怎麼存**

| 做法 | 取捨 | 結果 |
|---|---|---|
| A. 即時計算加人資調整表 | 不存餘額；額度由規則算、已用由申請加總、手動增減放調整表。只有一個資料來源，年度結束不需要排程工作 | **採用** |
| B. 流水帳（Frappe HRMS） | 稽核最完整；但每年「發」特休需要排程工作，系統沒有，只能在查詢時補寫，規則分散兩處 | 不採用 |
| C. 餘額欄位 | 讀取最簡單；任何一個路徑忘了更新就對不起來，年度重置也需要排程工作 | 不採用 |

**時間軸的請假資料**

| 做法 | 取捨 | 結果 |
|---|---|---|
| 請假模組提供 `GET /api/leave/calendar`，前端來源呼叫它 | 跟時間軸設計「前端彙整、權限由模組 API 負責」一致；假別的隱私在後端決定 | **採用** |
| 前端用 `GET /requests?scope=all` | 只有人資能用，一般員工的時間軸會是空的 | 不採用 |

## 設計

### 模組

`backend/app/modules/leave/`：`manifest.py`、`migrations/0001_leave.sql`、`rules.py`（純函式）、`service.py`（假別、額度、餘額、報表）、`requests.py`（申請的流程、行事曆、不可用提供者）、`router.py`。依賴 `org`、`core`、`booking`（送出申請時要查本人同時段的會議）。權限 `leave.request`、`leave.manage`。

### 資料表

**`leave_types` 假別**

| 欄位 | 說明 |
|---|---|
| `id` | identity |
| `code` | `text NOT NULL UNIQUE`，例如 `annual`、`personal` |
| `name` | 中文名稱 |
| `paid_ratio` | `numeric(3,2)`，`CHECK (paid_ratio BETWEEN 0 AND 1)`；給之後的薪資模組參考，這個模組不使用 |
| `quota_kind` | `seniority`／`yearly_cap`／`none` |
| `annual_cap_hours` | `int NULL`；`CHECK ((quota_kind = 'yearly_cap') = (annual_cap_hours IS NOT NULL))`，且大於 0 |
| `is_active` | 停用後不能再申請，舊申請不受影響 |

`seniority` 只能有一筆：`CREATE UNIQUE INDEX … ON leave_types (quota_kind) WHERE quota_kind = 'seniority'`。

遷移預載（參考資料，不是示範資料）：

| code | 名稱 | quota_kind | 上限（小時） | paid_ratio |
|---|---|---|---|---|
| `annual` | 特休 | seniority | — | 1 |
| `personal` | 事假 | yearly_cap | 112 | 0 |
| `sick` | 病假 | yearly_cap | 240 | 0.5 |
| `menstrual` | 生理假 | yearly_cap | 24 | 0.5 |
| `marriage` | 婚假 | yearly_cap | 64 | 1 |
| `paternity` | 陪產檢及陪產假 | yearly_cap | 56 | 1 |
| `bereavement` | 喪假 | none | — | 1 |
| `official` | 公假 | none | — | 1 |
| `maternity` | 產假 | none | — | 1 |

**`leave_requests` 請假申請**

| 欄位 | 說明 |
|---|---|
| `id` | identity |
| `employee_id` | `REFERENCES employees` |
| `leave_type_id` | `REFERENCES leave_types` |
| `start_at`、`end_at` | `timestamp`（不含時區，跟排程一樣：系統是單一時區），`CHECK (end_at > start_at)`；整點由 service 檢查 |
| `hours` | `int NOT NULL CHECK (hours > 0)`；送出時算好的快照 |
| `reason` | `text NOT NULL DEFAULT ''` |
| `status` | `pending`／`approved`／`rejected`／`withdrawn`／`cancelled` |
| `decided_by` | `int NULL REFERENCES users`；核准或退回的人 |
| `decided_at`、`decision_note` | 退回時 `decision_note` 必填（service 檢查） |
| `cancelled_by`、`cancelled_at` | 取消或撤回的人與時間 |
| `created_by`、`created_at` | 申請人帳號與時間 |

排除限制：同一個人在 `pending`、`approved` 的申請時段不能重疊。

```sql
EXCLUDE USING gist (employee_id WITH =, tsrange(start_at, end_at) WITH &&)
  WHERE (status IN ('pending', 'approved'))
```

索引：`(employee_id, start_at)`、`(status)`。

**`leave_adjustments` 額度調整**

| 欄位 | 說明 |
|---|---|
| `id` | identity |
| `employee_id`、`leave_type_id` | 外鍵；假別不能是 `none` |
| `period_start` | 調整哪一個年度：特休是該週年的開始日，其他假別是該年 1 月 1 日。service 檢查它是一個真的年度開始日 |
| `hours` | `int NOT NULL CHECK (hours <> 0)`，可正可負 |
| `reason` | `text NOT NULL`，不可空白 |
| `created_by`、`created_at` | |

調整不能修改或刪除，要更正就再加一筆反向的。

### 計算規則（`rules.py`，純函式）

**上班時間**：模組常數，週一到週五 09:00–12:00、13:00–18:00，一天 8 小時。`calendar_days` 的 `holiday` 不上班，`makeup_workday` 要上班（即使是週末）。排班模組做好後改成依班表，這裡留一句註解說明原因。

**時數** `countLeaveHours(startAt, endAt, calendarDays) -> int`：區間與每個上班日的兩段上班時間取交集再加總。開始、結束都必須是整點，否則丟錯。

**特休年度** `seniorityPeriod(hiredOn, day) -> (periodStart, periodEnd, days) | None`（週年制，勞基法第 38 條）：

| 年資 | 年度 | 天數 |
|---|---|---|
| 未滿 6 個月 | — | 沒有特休（回傳 `None`） |
| 6 個月以上、未滿 1 年 | 到職＋6 個月 ～ 到職＋1 年 | 3 |
| 1 年以上、未滿 2 年 | 第 1 個週年 ～ 第 2 個週年 | 7 |
| 2 年 | | 10 |
| 3、4 年 | | 14 |
| 5～9 年 | | 15 |
| 10 年以上 | | 15＋(年資－9)，最多 30 |

一天換算 8 小時。「到職＋N 個月」遇到月底沒有對應日期（例如 8/31＋6 個月）時，取該月最後一天。

**年度** `periodFor(leaveType, hiredOn, day)`：特休用上面的週年；其他假別用曆年。

**餘額** `balance = 規則額度 + 該年度調整加總 - 該年度 pending 與 approved 申請的時數`。`none` 只回傳已用時數，沒有額度與剩餘。

**一張申請只能屬於一個年度**：開始和結束要落在同一個年度，否則擋下並提示拆成兩張。判斷用 `start_at` 的日期，以及 `end_at` 前一刻的日期。

### 權限與核准

`permissions.py`：

- `_baseline` 加上 `leave.request`（員工、主管、人資、管理員都有）
- `_hr` 加上 `leave.manage`（人資、管理員）

**核准人**（service 判斷，不看角色）：

- 申請人的 `manager_id` 指向的員工，且該員工 `is_active`、有帳號
- 有 `leave.manage` 的人可以核准任何人
- **任何人都不能核准自己的申請**，包含人資
- 申請人沒有主管、或主管已離職時，只有 `leave.manage` 的人能核准

**看得到誰的資料**：本人；直屬主管看直屬下屬；有 `leave.manage` 的人看所有人。

### API（`/api/leave`）

| 端點 | 權限 | 說明 |
|---|---|---|
| `GET /types` | `leave.request` | 預設只列啟用的；`includeInactive=true` 需要 `leave.manage` |
| `POST /types`、`PATCH /types/{id}` | `leave.manage` | `quota_kind` 建立後不能改（改了會讓舊申請的年度算法變掉） |
| `GET /balances?employeeId=&on=` | `leave.request` | 預設本人、今天。每個啟用假別回傳 `periodStart`、`periodEnd`、`quotaHours`、`adjustmentHours`、`approvedHours`、`pendingHours`、`remainingHours`（`none` 的額度與剩餘是 `null`）。到職未滿 6 個月的特休回傳 `periodStart: null` 與 0 |
| `POST /requests/quote` | `leave.request` | body 同送出。不存檔，回傳 `hours`、`remainingAfter`、`conflicts`（會議重疊）。檢查錯誤時回傳跟送出一樣的錯誤 |
| `POST /requests` | `leave.request` | body `leaveTypeId`、`startAt`、`endAt`、`reason`、`acknowledgeWarnings`。只能替自己申請 |
| `GET /requests?scope=mine\|toApprove\|all&status=&from=&to=` | `leave.request`；`all` 需要 `leave.manage` | `toApprove`：直屬下屬的 `pending`；有 `leave.manage` 的人另外加上「沒有主管或主管已離職」的 `pending` |
| `GET /requests/{id}` | 看得到該員工的人 | |
| `POST /requests/{id}/approve` | 核准人 | body `note`（選填） |
| `POST /requests/{id}/reject` | 核准人 | body `note`（必填） |
| `POST /requests/{id}/withdraw` | 本人 | 只限 `pending` |
| `POST /requests/{id}/cancel` | 本人（開始前）或 `leave.manage` | 只限 `approved` |
| `GET /adjustments?employeeId=` | `leave.manage` | |
| `POST /adjustments` | `leave.manage` | |
| `GET /unused?periodEndFrom=&periodEndTo=` | `leave.manage` | 特休年度結束日落在區間內、剩餘大於 0 的人：員工、部門、年度、額度、已用、未休 |
| `GET /calendar?from=&to=` | `leave.request` | 區間內所有 `pending`、`approved` 的假：`id`、`employeeId`、`startAt`、`endAt`、`status`；`leaveTypeName` 只有本人、直屬主管、`leave.manage` 拿得到，其他人是 `null`。給時間軸用，區間最多 31 天 |

錯誤沿用平台的統一格式。新的錯誤代碼：`LEAVE_QUOTA_EXCEEDED`（附 `remainingHours`）、`LEAVE_OVERLAP`（排除限制，附重疊的申請）、`LEAVE_CROSSES_PERIOD`、`LEAVE_NO_WORKING_HOURS`、`LEAVE_NOT_ELIGIBLE`（到職未滿 6 個月請特休、早於到職日、員工已離職）、`NO_EMPLOYEE`（帳號沒有對應的員工，例如只有管理員帳號）、`LEAVE_INVALID_STATE`、`MEETING_CONFLICT`（409，附 `conflicts`，用 `acknowledgeWarnings` 略過）。

### 送出與狀態變更的流程

**送出**（一個交易）：

1. `SELECT … FROM employees WHERE id = %s FOR UPDATE`：同一個人的申請排隊檢查，兩張同時送出不會都通過額度
2. 員工 `is_active`；假別啟用；整點；`start_at` 不早於 `hired_on`；可以是過去的日期（病假常事後補）
3. 找年度、不能跨年度、特休要有年度（先做，避免超長區間在鎖內逐日算時數）
4. 算時數，等於 0 時擋下
5. 檢查額度（`none` 不檢查）
6. 沒有 `acknowledgeWarnings` 時，查本人同時段 `confirmed` 的會議，有就回 `MEETING_CONFLICT`
7. 寫入；排除限制擋下時轉成 `LEAVE_OVERLAP`
8. 寫稽核

**核准**：鎖住申請列與員工列，確認 `pending`、確認是核准人、**重新檢查額度**（送出後人資可能調低額度），寫入、寫稽核。核准不再檢查會議衝突。

**退回、撤回、取消**：鎖住申請列，確認狀態與身分，寫入、寫稽核。取消時「還沒開始」以伺服器現在時間和 `start_at` 比較。

### 接上資源預約

`leave` 模組載入時呼叫 `registerUnavailabilityProvider("leave", …)`：回傳指定員工在區間內 `pending`、`approved` 的假，`reason` 是「請假」或「請假（待核准）」，不帶假別。資源預約模組不改。

### 前端

`frontend/src/modules/leave/`，登記方式同其他模組。

**「請假」頁**（`/leave`，`leave.request`）

- 上方：我的餘額卡片，每個啟用假別一張。顯示剩餘時數，已用與待核准分開；特休顯示年度起訖；`none` 只顯示已用。
- 分頁「我的申請」：表格（假別、時間、時數、狀態）、撤回與取消按鈕依狀態與時間顯示；點列開詳情面板（事由、核准人、決定時間、備註）。
- 「申請請假」按鈕開表單：假別、開始日期＋整點、結束日期＋整點、事由。欄位變動後呼叫 `quote`（短暫延遲再送），顯示「共 N 小時，送出後剩 M 小時」或錯誤訊息。`MEETING_CONFLICT` 用跟資源預約一樣的警告樣式與「仍要送出」流程（請假模組自己的元件，不改資源預約的 `ConflictNotice`）。
- 分頁「待我核准」：`toApprove` 有資料、或使用者有 `leave.manage` 時才出現。核准；退回要填理由。

**「假別與額度」頁**（`/leave/admin`，`leave.manage`）

- 分頁「假別」：列表、新增、修改、停用
- 分頁「額度調整」：選員工後列出調整紀錄；新增時選假別、年度（由餘額 API 帶出該員工的年度選項）、時數、原因
- 分頁「未休特休」：選期間，列出結果

**首頁**：「待審核請假」方塊，只在 `toApprove` 有資料時顯示，點了到「待我核准」分頁。

**稽核頁**：模組篩選加 `leave`。

### 時間軸（最後一個任務）

- `TimelineItem.kind` 加 `"block"`：區塊畫法，跟 `event` 的長條分開。顏色依種類分（時間軸設計的規則）；待核准用文字「待核准」加淡色區分。
- `TimelineItem.link` 改成選填：沒有連結的項目畫成不能點的區塊。
- 時間軸頁加「檢視」選單（網址參數 `view`），在看得到的檢視之間切換；第一版只取第一個檢視的寫法拿掉。
- 請假跨好幾天時，中間那幾天會蓋滿 00:00–24:00，把時間軸撐成整天。請假來源把每筆假裁到當天的上班時間（09:00–18:00）再交給時間軸，當天沒有交集就不畫。
- 組織模組登記「員工」檢視：`subjectType: "employee"`、`requires: "org.read"`，列出在職員工，依部門分組。沒有 `createLink`。
- 請假模組登記「請假」來源：`subjectType: "employee"`，呼叫 `GET /api/leave/calendar`，`label` 是假別名稱或「請假」，`link` 到請假詳情（看不到詳情的人不給連結）。`queryKey` 放在 `["leave", …]` 底下，寫入後的 invalidate 會一併更新時間軸。
- 同一個人的請假由資料庫保證不重疊，所以員工檢視不需要疊放。

## 測試

**後端，純函式（`rules.py`）**

- 特休年資表的每個邊界：到職滿 6 個月前一天與當天、滿 1 年前一天與當天、第 2、3、5、10 年、第 24 年到 30 天、第 30 年仍是 30 天
- 8/31、2/29 到職的「＋6 個月」與週年日
- 時數：同一天跨午休、跨週末、遇到假日、遇到週末的補班日、非整點丟錯、全部落在非上班時間得 0
- 跨年度判斷：特休週年日、12/31 跨到 1/1、結束在 00:00 不算跨年度

**後端，service 與 API（真的 PostgreSQL，沿用現有測試的做法）**

- 額度：剛好用完通過、多 1 小時擋下；待核准也算進去；調整加減後生效；核准時額度已不足會擋下
- 同時送出兩張、各自不超過但加起來超過：只有一張成功
- 重疊申請由資料庫擋下；撤回或退回的申請不擋新申請
- 權限：非直屬主管不能核准；不能核准自己；主管離職後只有人資能核准；員工看不到別人的餘額；`calendar` 對一般員工不回傳假別
- 狀態轉換：每個不合法的轉換回 `LEAVE_INVALID_STATE`；本人在假開始後不能取消、人資可以
- 「不可用」提供者：排會議時，請假中的參加者出現在警告裡
- 每個寫入都有稽核紀錄
- 遷移：預載九個假別；`seniority` 第二筆被唯一索引擋下

**前端（Vitest）**

- 申請表單：欄位變動呼叫 `quote` 並顯示時數與剩餘；超額時顯示錯誤、不能送出；會議衝突時出現「仍要送出」
- 「待我核准」分頁依資料與權限出現或隱藏；退回沒填理由不能送出
- 首頁方塊只在有待核准時出現
- 時間軸：`block` 項目畫成區塊；員工檢視依部門分組；看不到假別時顯示「請假」

## 怎麼驗證

1. 啟動系統，以一般員工登入，到「請假」頁：看得到特休、事假等餘額。
2. 申請明天 09:00–18:00 的事假：表單顯示「共 8 小時」，送出後狀態是待核准，事假剩餘少 8 小時。
3. 以他的主管登入：首頁出現「待審核請假」方塊，進去核准。
4. 以任何人排一場明天、有這位員工參加的會議：出現「請假」的參加者警告。
5. 到時間軸切到「員工」檢視：這位員工明天有一塊請假；以另一位一般員工登入時只顯示「請假」，不顯示「事假」。
6. 以人資登入「假別與額度」：替他加 8 小時事假額度，回到他的餘額看到增加。

## 留給建造者決定

- 餘額卡片、表單、分頁的版面細節，照原型風格即可
- `quote` 的延遲時間
- 「未休特休」報表的預設期間
- 時間軸 `block` 的確切樣式（不要跟 `event` 撞色）

## 已回答的問題（2026-11-21）

- 請假單位：**小時**，排班做好前用固定上班時間
- 假別：**年度上限型**，依事件的條件不做成規則
- 核准：**直屬主管一關**，人資可代核、沒有主管時由人資核准
- 特休年度：**週年制**
- 未休特休：**只記錄不遞延**
- 取消已核准的假：**開始前本人可取消**，開始後只有人資
- 額度與餘額：**即時計算加人資調整表**
- 時間軸：**放進這次，排最後一個任務**
