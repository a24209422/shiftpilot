"""新表（部門、員工、會議室細節、上班時段、請假、假日）的 test-ext 題目。

調 prompt 的人不看這份，只在最後驗收時跑一次；標準答案都已在 evals.fixture 的固定資料上實際跑過、結果非空。
日期以 fixture.fixedNow（2026-11-17 星期二 14:30）為準：本週 11-16 ～ 11-22、上週 11-09 ～ 11-15、下週 11-23 ～ 11-29。
出題原則沿用 cases.py 開頭的說明；類別見 ext_cases.py。
"""

extHeldoutCases = [
  # org：部門與主管
  {
    "id": "h-org01",
    "category": "org",
    "question": "營運部裡面誰最晚到職？",
    "goldSql": (
      "SELECT r.name FROM employees e "
      "JOIN departments d ON d.id = e.department_id "
      "JOIN resources r ON r.id = e.resource_id "
      "WHERE d.name = '營運部' ORDER BY e.hired_on DESC LIMIT 1"
    ),
  },
  {
    "id": "h-org02",
    "category": "org",
    "question": "總經理室底下的各個部門，各有幾個員工？",
    # 部門要自己 JOIN 自己才找得到上層；總經理室本身不算「底下」
    "goldSql": (
      "SELECT d.name, COUNT(e.id) FROM departments d "
      "JOIN departments p ON p.id = d.parent_id "
      "JOIN employees e ON e.department_id = d.id "
      "WHERE p.name = '總經理室' GROUP BY d.name"
    ),
  },
  {
    "id": "h-org03",
    "category": "org",
    "question": "哪些員工跟自己的主管不在同一個部門？",
    "compareAsSet": True,
    "goldSql": (
      "SELECT r.name FROM employees e "
      "JOIN employees m ON m.id = e.manager_id "
      "JOIN resources r ON r.id = e.resource_id "
      "WHERE e.department_id <> m.department_id"
    ),
  },
  # room：會議室細節加上排程
  {
    "id": "h-room01",
    "category": "room",
    "question": "要開 10 個人的會議，哪些會議室坐得下？",
    "compareAsSet": True,
    "goldSql": (
      "SELECT r.name FROM rooms ro "
      "JOIN resources r ON r.id = ro.resource_id "
      "WHERE ro.capacity >= 10"
    ),
  },
  {
    "id": "h-room02",
    "category": "room",
    "question": "沒有視訊設備的會議室，這週排了哪些會議？列出會議標題和開始時間。",
    "goldSql": (
      "SELECT e.title, e.start_at FROM events e "
      "JOIN event_resources er ON er.event_id = e.id "
      "JOIN rooms ro ON ro.resource_id = er.resource_id "
      "WHERE ro.has_video_conference = FALSE AND e.category = 'meeting' "
      "AND e.start_at >= '2026-11-16' AND e.start_at < '2026-11-23'"
    ),
  },
  {
    "id": "h-room03",
    "category": "room",
    "question": "樓層最高的那間會議室，下週排了哪些會議？",
    "goldSql": (
      "SELECT e.title FROM events e "
      "JOIN event_resources er ON er.event_id = e.id "
      "JOIN rooms ro ON ro.resource_id = er.resource_id "
      "WHERE ro.floor = (SELECT MAX(floor) FROM rooms) "
      "AND e.start_at >= '2026-11-23' AND e.start_at < '2026-11-30'"
    ),
  },
  # hours：上班時段與假日
  {
    "id": "h-hours01",
    "category": "hours",
    "question": "王小明每週要上幾天班？",
    "goldSql": (
      "SELECT COUNT(*) FROM work_hours w "
      "JOIN employees e ON e.id = w.employee_id "
      "JOIN resources r ON r.id = e.resource_id "
      "WHERE r.name = '王小明'"
    ),
  },
  {
    "id": "h-hours02",
    "category": "hours",
    "question": "照王小明的固定上班時段，行憲紀念日那天他原本是幾點上班？",
    # 假日只有日期，要用 ISODOW 換成星期幾才接得上 work_hours.weekday
    "goldSql": (
      "SELECT w.start_time FROM holidays h "
      "JOIN work_hours w ON w.weekday = EXTRACT(ISODOW FROM h.day) "
      "JOIN employees e ON e.id = w.employee_id "
      "JOIN resources r ON r.id = e.resource_id "
      "WHERE h.name = '行憲紀念日' AND r.name = '王小明'"
    ),
  },
  {
    "id": "h-hours03",
    "category": "hours",
    "question": "哪些員工沒有固定的上班時段？",
    "compareAsSet": True,
    "goldSql": (
      "SELECT r.name FROM employees e "
      "JOIN resources r ON r.id = e.resource_id "
      "WHERE NOT EXISTS (SELECT 1 FROM work_hours w WHERE w.employee_id = e.id)"
    ),
  },
  # leave：請假區間重疊、審核狀態
  {
    "id": "h-leave01",
    "category": "leave",
    "question": "陳大文已經核准的請假有幾筆？",
    "goldSql": (
      "SELECT COUNT(*) FROM leave_requests l "
      "JOIN employees e ON e.id = l.employee_id "
      "JOIN resources r ON r.id = e.resource_id "
      "WHERE r.name = '陳大文' AND l.status = 'approved'"
    ),
  },
  {
    "id": "h-leave02",
    "category": "leave",
    "question": "下週四有誰請假？",
    "compareAsSet": True,
    # 假單跨好幾天，開始和結束都不在那一天，所以比的是區間有沒有重疊
    "goldSql": (
      "SELECT r.name FROM leave_requests l "
      "JOIN employees e ON e.id = l.employee_id "
      "JOIN resources r ON r.id = e.resource_id "
      "WHERE l.status = 'approved' "
      "AND l.start_at < '2026-11-27' AND l.end_at > '2026-11-26'"
    ),
  },
  {
    "id": "h-leave03",
    "category": "leave",
    "question": "哪些員工沒有任何一筆核准的請假紀錄？",
    "compareAsSet": True,
    "goldSql": (
      "SELECT r.name FROM employees e "
      "JOIN resources r ON r.id = e.resource_id "
      "WHERE NOT EXISTS ("
      "SELECT 1 FROM leave_requests l "
      "WHERE l.employee_id = e.id AND l.status = 'approved')"
    ),
  },
  # combo：排程結合新表
  {
    "id": "h-combo01",
    "category": "combo",
    "question": "營運部下週有誰要上晚班？",
    "compareAsSet": True,
    "goldSql": (
      "SELECT r.name FROM events e "
      "JOIN event_resources er ON er.event_id = e.id "
      "JOIN employees emp ON emp.resource_id = er.resource_id "
      "JOIN resources r ON r.id = emp.resource_id "
      "JOIN departments d ON d.id = emp.department_id "
      "WHERE d.name = '營運部' AND e.category = 'shift' AND e.title = '晚班' "
      "AND e.start_at >= '2026-11-23' AND e.start_at < '2026-11-30'"
    ),
  },
  {
    "id": "h-combo02",
    "category": "combo",
    "question": "李小華的主管這週有哪些會議？",
    "goldSql": (
      "SELECT e.title FROM resources xr "
      "JOIN employees x ON x.resource_id = xr.id "
      "JOIN employees m ON m.id = x.manager_id "
      "JOIN event_resources er ON er.resource_id = m.resource_id "
      "JOIN events e ON e.id = er.event_id "
      "WHERE xr.name = '李小華' AND e.category = 'meeting' "
      "AND e.start_at >= '2026-11-16' AND e.start_at < '2026-11-23'"
    ),
  },
  {
    "id": "h-combo03",
    "category": "combo",
    "question": "有沒有人請假被駁回，而且請假的那段時間剛好排了班？列出是誰和排的班別。",
    # 假單與班別的時間區間有重疊就算，不要求兩邊剛好一樣長
    "goldSql": (
      "SELECT r.name, e.title FROM leave_requests l "
      "JOIN employees emp ON emp.id = l.employee_id "
      "JOIN resources r ON r.id = emp.resource_id "
      "JOIN event_resources er ON er.resource_id = r.id "
      "JOIN events e ON e.id = er.event_id "
      "WHERE l.status = 'rejected' AND e.category = 'shift' "
      "AND e.start_at < l.end_at AND e.end_at > l.start_at"
    ),
  },
]
