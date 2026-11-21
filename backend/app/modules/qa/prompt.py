import json
from datetime import datetime, timedelta

from app.modules.qa.sandbox import SandboxData

weekdayNames = ["一", "二", "三", "四", "五", "六", "日"]
answerSampleRows = 30

schemaText = """\
departments(id, name, parent_id)：部門
employees(id, employee_no, name, department_id, job_title, manager_id, hired_on)：在職員工；manager_id 是直屬主管的 employees.id
resources(id, name, kind, location, capacity)：資源；kind 是 room（會議室）、equipment（設備）、vehicle（公務車）
bookings(id, title, category, start_at, end_at)：已確認的排程（會議、活動）
booking_resources(booking_id, resource_id)：排程用到的資源
booking_participants(booking_id, employee_id, role)：排程的參加者；role 是 organizer（主辦）或 attendee
leave_requests(id, employee_id, leave_type, start_at, end_at, hours, status, reason)：請假；status 是 pending（待核准）、approved（已核准）、rejected、withdrawn、cancelled。leave_type 與 reason 是 NULL 代表提問者沒有權限看，回答時只能說「請假」
day_shifts(employee_id, day, shift_name, start_at, end_at, break_start_at, break_end_at, source)：每人每天的班；休息日的 shift_name 與時間都是 NULL；跨日班算在開始那天，end_at 在隔天
busy_periods(employee_id, start_at, end_at, kind, label)：每人的忙碌時段；kind 是 meeting（label 是排程標題）或 leave（label 是「請假」或「請假（待核准）」）
calendar_days(day, kind, name)：kind 是 holiday（國定假日）或 makeup_workday（補班日）"""


def buildDateReference(now: datetime) -> str:
  # 小模型很不會算「下週三」是哪天，直接把日期表給它查
  today = now.date()
  monday = today - timedelta(days=today.weekday())
  lines = [
    f"今天是 {today} 星期{weekdayNames[today.weekday()]}，現在時間 {now.strftime('%H:%M')}。一週從星期一開始。",
    f"本週：{monday} ～ {monday + timedelta(days=6)}",
    f"下週：{monday + timedelta(days=7)} ～ {monday + timedelta(days=13)}",
    f"上週：{monday - timedelta(days=7)} ～ {monday - timedelta(days=1)}",
  ]
  relativeNames = {-1: "昨天", 0: "今天", 1: "明天", 2: "後天"}
  for offset in range(-1, 14):
    day = today + timedelta(days=offset)
    label = f"（{relativeNames[offset]}）" if offset in relativeNames else ""
    lines.append(f"{day} 星期{weekdayNames[day.weekday()]}{label}")
  return "\n".join(lines)


def fewShots(now: datetime) -> list[tuple[str, str]]:
  # 範例的日期跟著今天變，模型才學得到「明天」「下週」要換成實際日期
  today = now.date()
  tomorrow = today + timedelta(days=1)
  monday = today - timedelta(days=today.weekday())
  nextWednesday = monday + timedelta(days=9)
  return [
    (
      "黃志強明天上什麼班？",
      "SELECT employees.name, day_shifts.day, day_shifts.shift_name, day_shifts.start_at, day_shifts.end_at\n"
      "FROM day_shifts JOIN employees ON employees.id = day_shifts.employee_id\n"
      f"WHERE employees.name LIKE '%黃志強%' AND day_shifts.day = '{tomorrow}'",
    ),
    (
      "下週三下午兩點到三點誰有空？",
      "SELECT employees.name\n"
      "FROM employees JOIN day_shifts ON day_shifts.employee_id = employees.id\n"
      f"WHERE day_shifts.start_at <= '{nextWednesday} 14:00' AND day_shifts.end_at >= '{nextWednesday} 15:00'\n"
      "  AND NOT EXISTS (\n"
      "    SELECT 1 FROM busy_periods WHERE busy_periods.employee_id = employees.id\n"
      f"      AND busy_periods.start_at < '{nextWednesday} 15:00' AND busy_periods.end_at > '{nextWednesday} 14:00')\n"
      "ORDER BY employees.name",
    ),
    # 前兩題都有日期條件，小模型會照抄，連沒問日期的題目也加上日期範圍；這題刻意不帶日期
    (
      "工程部有哪些人？",
      "SELECT employees.name, employees.job_title\n"
      "FROM employees JOIN departments ON departments.id = employees.department_id\n"
      "WHERE departments.name LIKE '%工程部%'\nORDER BY employees.employee_no",
    ),
    (
      "這週誰請假？",
      "SELECT DISTINCT employees.name\n"
      "FROM leave_requests JOIN employees ON employees.id = leave_requests.employee_id\n"
      f"WHERE leave_requests.status IN ('pending', 'approved') AND leave_requests.start_at < '{monday + timedelta(days=7)}'\n"
      f"  AND leave_requests.end_at > '{monday}'",
    ),
  ]


def buildSqlMessages(question: str, data: SandboxData, now: datetime) -> list[dict]:
  vocabulary = data.vocabulary
  systemPrompt = f"""你是 PostgreSQL 專家，負責把使用者的中文問題轉成一句 PostgreSQL 查詢。

規則：
1. 只輸出一句 SELECT（或 WITH ... SELECT），放在 ```sql 區塊裡，不要任何解釋。
2. 只能使用下方的資料表與欄位。
3. 時間欄位是 timestamp，日期欄位是 date；可以直接跟 'YYYY-MM-DD'、'YYYY-MM-DD HH:MM' 格式的字串比較。
4. 不要用 CURRENT_DATE 或 now()，日期一律以下方「日期參考」為準。
5. 比對名稱時用 LIKE '%關鍵字%'，因為使用者常只講部分名字。
6. 計算「幾筆」「幾個人」時用 COUNT(DISTINCT ...)。
7. 判斷某段時間誰有空：day_shifts 的班要蓋住那段時間，而且 busy_periods 在那段時間沒有重疊。
8. 資料只涵蓋 {data.windowStart} ～ {data.windowEnd}，超出範圍的日期查不到資料。

## 資料表
{schemaText}

## 目前資料中的值
- 部門：{', '.join(vocabulary['departments']) or '（尚無）'}
- 班別：{', '.join(vocabulary['shifts']) or '（尚無）'}
- 假別：{', '.join(vocabulary['leaveTypes']) or '（尚無）'}
- 資源：{', '.join(vocabulary['resources']) or '（尚無）'}

## 日期參考
{buildDateReference(now)}
"""
  messages = [{"role": "system", "content": systemPrompt}]
  for exampleQuestion, exampleSql in fewShots(now):
    messages.append({"role": "user", "content": exampleQuestion})
    messages.append({"role": "assistant", "content": f"```sql\n{exampleSql}\n```"})
  messages.append({"role": "user", "content": question})
  return messages


def buildAnswerMessages(question: str, columns: list[str], rows: list[list], rowCount: int, truncated: bool) -> list[dict]:
  sample = rows[:answerSampleRows]
  total = f"{rowCount} 筆以上" if truncated else f"{rowCount} 筆"
  lines = "\n".join(json.dumps(row, ensure_ascii=False) for row in sample) or "（沒有資料）"
  return [
    {
      "role": "system",
      "content": "你是公司內部系統的助理。根據查詢結果，用一到兩句正體中文（台灣用語）回答使用者的問題。"
      "只能使用查詢結果裡的資訊，不要猜測，不要提到 SQL 或資料表。查詢結果是空的就回答查無資料。名單太長時列出前幾位並說明總數。",
    },
    {"role": "user", "content": f"問題：{question}\n欄位：{', '.join(columns)}\n總筆數：{total}\n前 {len(sample)} 列：\n{lines}"},
  ]
