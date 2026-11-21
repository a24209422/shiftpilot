# 設計：排班模組

日期：2026-11-21　｜　規模：子專案（平台設計的第 3 塊）　｜　狀態：**待審閱**

前一份：`2026-11-20-erp-platform-design.md`（子專案順序第 3 項）、`2026-11-21-leave-design.md`（「依班表算時數：排班模組做好之前用固定上班時間」）、`2026-11-20-timeline-design.md`（「班表用『狀態』（整列底色）」）。

## 目的

公司以辦公室為主：多數人固定上標準班 09:00–18:00，少數人（客服、值班）有早晚班或輪班。這個模組讓系統知道「誰在哪一天幾點上班」，並用在三個地方：

1. **請假時數**依那個人那天的班計算，取代請假模組寫死的 09:00–18:00
2. **排會議**時，參加者不在班就警告
3. **時間軸**的員工檢視用底色畫出上班時段，請假區塊也依班裁切

## 範圍

**做**

- 後端模組 `shift`：班別、週班表、單日調整；即時推算每人每天的班；直屬主管與人資可以排班
- 「不可用」提供者：會議落在參加者的班外時警告
- 請假模組改成依班計算時數；`/api/leave/calendar` 回傳依班裁切的片段
- 前端「班表」頁（一週表格）、「班別」管理頁
- 時間軸新增 `status` 種類，排班模組登記員工列的上班底色
- 稽核頁的模組篩選加上 `shift`

**不做**

- 換班申請與核准流程
- 週期輪班樣板（例如「早早晚晚休休」循環）
- 加班、打卡、出勤
- 最低人力檢查
- 勞基法工時檢查（七休一、每日工時上限等）
- 示範用的班表資料

## 做法比較

**「某人某天幾點上班」怎麼得到**

| 做法 | 取捨 | 結果 |
|---|---|---|
| A. 即時推算 | 不存每天的班，由「預設班 → 週班表 → 單日調整 → 行事曆假日」推算。換班表後，之後的日子自動跟著變；跟請假模組「餘額不存」同一套思路 | **採用** |
| B. 預先展開成每日班表 | 查詢最簡單；但換班表、改假日都要重新產生，需要排程工作，資料容易對不起來 | 不採用 |

**請假怎麼拿到上班時段**

| 做法 | 取捨 | 結果 |
|---|---|---|
| A. 請假模組直接依賴排班模組 | 排班比請假底層（「誰幾點上班」是請假的前提），模組順序 org → shift → leave；假日與補班日規則只寫在排班一處 | **採用** |
| B. 平台新增「上班時段提供者」接口 | 請假不知道排班的存在；但只會有一個提供者，等於為「之後可能要」多做一層（時間軸設計書以同樣理由不採用後端彙整） | 不採用 |

## 設計

### 模組

`backend/app/modules/shift/`：`manifest.py`、`migrations/0001_shift.sql`、`rules.py`（純函式）、`service.py`（班別、週班表、單日調整、推算、上班時段）、`router.py`（API 與 `onAppCreated` 登記不可用提供者）。依賴 `org`、`core`。權限 `shift.read`、`shift.manage`。

請假模組的 `dependsOn` 加上 `shift`。

### 資料表

**`shift_types` 班別**

| 欄位 | 說明 |
|---|---|
| `id` | identity |
| `code` | `text NOT NULL UNIQUE`，格式同請假假別（小寫英文開頭） |
| `name` | `text NOT NULL UNIQUE`，不可空白 |
| `start_time`、`end_time` | `time NOT NULL`，`CHECK (start_time <> end_time)`；必須是整點（請假的最小單位是 1 小時、時數存整數，半點的班會讓請假算出半小時）；`end_time < start_time` 代表跨過午夜，這種班算在**開始那天** |
| `break_start`、`break_end` | `time NULL`，`CHECK ((break_start IS NULL) = (break_end IS NULL))`；同樣必須是整點；休息時間必須完整落在班內（service 檢查，跨日班也要正確判斷） |
| `is_default` | 公司預設班，`CREATE UNIQUE INDEX … ON shift_types (is_default) WHERE is_default` 保證最多一筆 |
| `is_active` | 停用後不能再排進新的週班表或單日調整，已排的照舊 |

遷移預載一筆：`standard`／「標準班」／09:00–18:00／休息 12:00–13:00／預設班。

**`shift_rosters` 週班表**

| 欄位 | 說明 |
|---|---|
| `id` | identity |
| `employee_id` | `REFERENCES employees` |
| `effective_from` | `date NOT NULL`；`UNIQUE (employee_id, effective_from)` |
| `created_by`、`created_at` | |

一張週班表從生效日用到同一人下一張的生效日前一天。要換班表就新增一張；舊的保留，過去某天上什麼班一直查得回來。想回到預設班，就新增一張「週一到週五標準班」的班表。

**`shift_roster_days` 週班表的每一天**

| 欄位 | 說明 |
|---|---|
| `roster_id` | `REFERENCES shift_rosters ON DELETE CASCADE` |
| `weekday` | `int CHECK (weekday BETWEEN 0 AND 6)`，0＝週一 |
| `shift_type_id` | `REFERENCES shift_types` |
| | `PRIMARY KEY (roster_id, weekday)` |

沒有列出的星期幾就是休息。

**`shift_overrides` 單日調整**

| 欄位 | 說明 |
|---|---|
| `id` | identity |
| `employee_id` | `REFERENCES employees` |
| `day` | `date NOT NULL`；`UNIQUE (employee_id, day)` |
| `shift_type_id` | `NULL` 代表那天休息 |
| `note` | `text NOT NULL DEFAULT ''` |
| `created_by`、`created_at`、`updated_by`、`updated_at` | |

單日調整可以修改、刪除，每次都寫稽核紀錄。

### 推算規則（`rules.py`，純函式）

`resolveDay(day, employee, override, roster, calendarKind, defaultShift) -> ResolvedDay`，依序判斷，先符合的算數：

1. 到職日之前、`left_on` 之後，或停用且沒有 `left_on` → `source: "inactive"`，休息（有 `left_on` 時，離職前的日子照常推算，歷史才查得回來）
2. 有單日調整 → `source: "override"`，照調整（`shift_type_id` 為空就是休息）
3. 行事曆是 `holiday` → `source: "holiday"`，休息（帶假日名稱）
4. 有生效中的週班表 → `source: "roster"`，用那個星期幾的班。那天是 `makeup_workday` 而班表那天休息 → 改用預設班（`source: "default"`）
5. 沒有週班表 → 週一到週五與 `makeup_workday` 上預設班（`source: "default"`），其他天 `source: "off"`

`ResolvedDay`：`day`、`source`、`shiftTypeId`、`shiftName`、`startAt`、`endAt`（跨日班的 `endAt` 在隔天）、`breakStartAt`、`breakEndAt`、`holidayName`、`overrideNote`。休息的日子班別相關欄位都是 `None`。

`workWindowsOf(resolved) -> list[(datetime, datetime)]`：班的起訖扣掉休息時間；標準班是 `[09:00–12:00, 13:00–18:00]`。休息時間跨過午夜時也要正確切開。

**沒有任何預設班時**（人資把預設班取消且沒有新的）：步驟 4、5 需要預設班的地方都當作休息。前端班別頁要提示「目前沒有預設班」。

### Service 接口

- `getSchedule(conn, employeeIds: list[int] | None, startDay: date, endDay: date) -> list[dict]`：一次查出需要的員工、週班表、單日調整、行事曆與班別，逐日呼叫 `resolveDay`。`employeeIds` 為 `None` 時是所有在職員工。區間最多 31 天。
- `workWindows(conn, employeeIds: list[int], startAt: datetime, endAt: datetime) -> dict[int, list[(datetime, datetime)]]`：每人跟區間有交集的上班時段，已裁到區間內。一次查多人，請假的行事曆 API 才不用每筆假各查一次。查詢從 `startAt` 的前一天開始，才接得到前一晚延續過來的跨日班。給請假模組用。
- `shiftSpans(conn, employeeIds, startAt, endAt) -> dict[int, list[(datetime, datetime, ResolvedDay)]]`：每人跟區間有交集的「整個班」（不扣休息），給不可用提供者用。

### 權限

`permissions.py`：

- `_baseline` 加 `shift.read`（所有角色都可以看任何人的班；班表不算隱私，排會議、看時間軸要用）
- `_hr` 加 `shift.manage`（人資、管理員）

**誰可以排某位員工的班**（service 判斷）：有 `shift.manage` 的人，或該員工 `manager_id` 指向的人。主管自己的班由人資排。

### API（`/api/shift`）

| 端點 | 權限 | 說明 |
|---|---|---|
| `GET /types` | `shift.read` | 預設只列啟用的；`includeInactive=true` 需要 `shift.manage` |
| `POST /types` | `shift.manage` | 起訖、休息時間在這裡決定 |
| `PATCH /types/{id}` | `shift.manage` | 只能改 `name`、`isActive`、`isDefault`。起訖與休息時間不能改：班是即時推算的，改了會讓過去的班跟著變；要換時間就新增班別、停用舊的。設成預設時原本的預設自動取消（同一個交易）；預設班不能停用 |
| `GET /rosters?employeeId=` | `shift.read` | 某人所有週班表，新到舊，含每天的班 |
| `POST /rosters` | 可排該員工的人 | body `employeeId`、`effectiveFrom`、`days: [{weekday, shiftTypeId}]`。生效日不能早於到職日；weekday 不能重複；班別要啟用 |
| `DELETE /rosters/{id}` | 可排該員工的人 | 只能刪生效日在今天之後的（更正排錯的）；已生效的不能刪 |
| `GET /overrides?employeeId=&from=&to=` | `shift.read` | |
| `PUT /overrides` | 可排該員工的人 | body `employeeId`、`day`、`shiftTypeId`（`null`＝休息）、`note`；有就修改、沒有就新增 |
| `DELETE /overrides/{employeeId}/{day}` | 可排該員工的人 | |
| `GET /schedule?from=&to=&employeeIds=` | `shift.read` | `from`、`to` 是日期（含頭含尾），最多 31 天；`employeeIds` 逗號分隔，省略是所有在職員工 |

錯誤代碼：`SHIFT_TYPE_IMMUTABLE`（改起訖或休息時間，422）、`SHIFT_DEFAULT_REQUIRED`（停用預設班，409）、`SHIFT_TYPE_INACTIVE`（排進停用的班別，422）、`ROSTER_ALREADY_EFFECTIVE`（刪已生效的週班表，409）、`ROSTER_BEFORE_HIRE`（422），重複的生效日沿用 `DUPLICATE`（409）。

每個寫入動作都寫稽核，模組名稱 `shift`。

### 串接請假

- `leave/rules.py`：拿掉 `workWindows` 常數與 `isWorkday`。`countLeaveHours(startAt, endAt, windows: list[(datetime, datetime)]) -> int` 改成「請假區間跟上班時段的交集加總」；`requireWholeHour` 保留。
- `leave/requests.py`：拿掉 `calendarKindsBetween`，改呼叫 `shift.service.workWindows(conn, [employeeId], startAt, endAt)`。流程與錯誤代碼不變；整段都不在班內仍然回 `LEAVE_NO_WORKING_HOURS`。
- `GET /api/leave/calendar`：每筆多回傳 `segments: [{startAt, endAt}]`，是那筆假跟上班時段的交集（已裁到查詢區間）。沒有交集的假仍然回傳，`segments` 是空陣列。
- 已送出的申請時數是快照，不受影響。
- **現有的請假測試要全部照舊通過**（員工沒有週班表就是標準班，結果應該跟原本的固定 09–18 一樣），再加上晚班、跨日班、單日調整成休息的案例。

### 串接排會議（不可用提供者）

`shift` 模組在 `router.py` 的 `onAppCreated` 登記 `registerUnavailabilityProvider("shift", …)`：

- 會議時段沒有被參加者的班（整個班的起訖，**不扣休息時間**：午餐時段開會很常見）完全蓋住，就回一筆警告
- 會議開始那天那人休息 → `reason`「休息日」；其他情況 → `reason`「不在班（14:00–23:00）」（括號內是那天的班）
- 不帶其他資訊。資源預約模組不改

### 前端

`frontend/src/modules/shift/`，登記方式同其他模組。

**「班表」頁**（`/shifts`，`shift.read`）

- 一週一張表格：列是員工（依部門分組），欄是週一到週日；上一週、本週、下一週（網址參數 `week`，跟排程頁一樣）
- 格子顯示班名與時間（例如「晚班 14–23」），休息顯示「休」，國定假日顯示假日名稱；單日調整的格子加標記，預設班的格子用較淡的樣式
- 點格子開詳情面板：日期、班、來源（預設班／週班表／單日調整／假日／休息／未在職）、調整備註。有權限的人看得到「設定單日調整」（班別或休息、備註）與「刪除調整」
- 點員工名字開週班表面板：週班表歷史（生效日、每天的班）；有權限的人看得到「新增週班表」（生效日、週一到週日各選班別或休息）與未生效班表的「刪除」
- 「有權限」= 有 `shift.manage`，或那位員工的 `managerId` 等於登入者的 `employeeId`（只決定顯示，後端另外檢查）

**「班別」頁**（`/shifts/types`，`shift.manage`）

- 列表（名稱、代碼、時間、休息、預設、狀態）、新增、改名稱、設為預設、停用／啟用
- 沒有預設班時在頁面上方提示

**稽核頁**：模組篩選加 `shift`。

### 時間軸

- `TimelineItem.kind` 加 `"status"`：畫在列的底層（在 `event`、`block` 之下）、淡底色、不能點，`title` 顯示班名與時間
- `shift` 模組登記來源：`subjectType: "employee"`、`requires: "shift.read"`，用 `/api/shift/schedule` 把每個上班時段（扣掉休息）轉成 `status` 項目。`queryKey` 放在 `["shifts", …]` 底下，排班的寫入 invalidate `["shifts"]`
- 請假來源改用 `/api/leave/calendar` 的 `segments`：每個片段一個區塊，不再在前端寫死 09:00–18:00。這也解掉請假設計 backlog 的「時間軸跨週末的假在週六日也畫區塊」

## 測試

**後端，純函式（`shift/rules.py`）**

- 推算的每一層：到職前、離職後、停用；單日調整（有班、休息）蓋過假日與週班表；假日；週班表換表的前一天與當天；補班日班表休息時退回預設班；沒有週班表的平日、週末、補班日；沒有預設班
- 跨日班：`endAt` 在隔天；休息時間跨過午夜時上班時段切對
- 班別的休息時間不在班內時被擋下

**後端，service 與 API**

- 主管只能排直屬下屬；員工不能排別人；人資可以排任何人；主管不能排自己
- 班別的起訖不能改；預設班唯一，設新預設時舊的自動取消；預設班不能停用；停用的班別不能排
- 已生效的週班表不能刪；生效日不能早於到職日；重複生效日回 `DUPLICATE`
- `/schedule` 的 `source` 與 31 天上限
- 不可用提供者：「休息日」、「不在班（…）」、完全在班內不警告、午餐時段不警告
- 請假：現有測試照舊通過；晚班的人請 14:00–23:00 得 8 小時（扣休息 1 小時）；跨日班；單日調整成休息那天請假得 0 小時；`calendar` 的 `segments`
- 每個寫入都有稽核

**前端（Vitest）**

- 週表格：格子內容、來源標記、換週
- 依權限出現「設定單日調整」「新增週班表」；直屬主管看得到、其他員工看不到
- 週班表表單送出的內容；單日調整設成休息
- 班別頁：新增、設為預設、停用；沒有預設班的提示
- 時間軸：`status` 畫在長條與區塊下面；請假依 `segments` 畫

## 怎麼驗證

以下以 2026-11-23（週一）那一週為例，用請假驗證時建立的測試帳號。

1. 人資（張雅婷）到「班別」新增「晚班」14:00–23:00、休息 18:00–19:00。
2. 到「班表」，點黃志強的名字，新增週班表：生效日 2026-11-23，週一到週五晚班。
3. 切到 11/23 那一週：黃志強每格顯示「晚班 14–23」、來源週班表；其他人是預設班。
4. 點林小美 11/24 那格，設定單日調整「休息」：格子變成「休」並有標記。
5. 用黃志強申請 11/24 14:00–23:00 事假：試算顯示「共 8 小時」。
6. 用陳大文排 11/25 10:00–11:00 的會議，邀黃志強：警告「黃志強：不在班（14:00–23:00）」。改成 11/24、邀林小美：警告「林小美：休息日」。
7. 時間軸切到「員工」、11/23：黃志強的列在 14:00–23:00 有底色（18–19 中斷），林小美在 09–12、13–18 有底色，她的事假區塊疊在上面。

## 留給建造者決定

- 週表格的格子樣式、預設班與調整的視覺區分，照原型風格即可
- `status` 底色的顏色（不要跟 `event`、`block` 撞色）
- 班表頁一次載入的員工數量很多時是否分頁（第一版不分頁）

## 已回答的問題（2026-11-21）

- 公司型態：**辦公室為主、少數輪班**；沒排班的人用預設班
- 指派方式：**週班表加單日調整**
- 國定假日：**不上班，要上班就用單日調整指定**
- 權限：**人資與直屬主管可以排班，所有人都看得到**
- 串接：**請假時數依班計算、排會議提醒不在班、時間軸畫班**，三項都做
- 做法：**即時推算（1A）**、**請假直接依賴排班（2A）**

## 實作後補充的決定（2026-11-22）

- **回溯排班**：只有人資（`shift.manage`）能新增生效日在今天以前的週班表、設定或刪除今天以前的單日調整；主管會得到 `SHIFT_PAST_DAY`（403）。過去的班會影響已核准請假的時數對照，更正歷史交給人資。
- **送出的人自己不提醒「不在班」**：排班提供者的警告帶 `selfExempt`，資源預約略過送出者本人的這類警告；請假、撞會等其他警告照常提醒，人資替別人排會時那位主辦人照常檢查。
