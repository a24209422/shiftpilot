"""新表（部門、員工、會議室細節、上班時段、請假、假日）的評測題目。

dev-ext 放在這裡的 extCases，調 prompt 時看；test-ext 在 ext_heldout_cases.py，由沒看過 dev 錯誤模式的 subagent 出題、
使用者抽查後凍結，之後不再修改，也不打開來看每題的細節。出題原則沿用 cases.py 開頭的說明。

日期以 fixture.fixedNow（2026-11-17 星期二 14:30）為準：本週 11-16 ～ 11-22、上週 11-09 ～ 11-15、下週 11-23 ～ 11-29。

| 類別 | 測什麼 | 例子 |
|---|---|---|
| org | 部門、主管：多層 JOIN、自己參照 | 「業務部有哪些人？」「陳大文的主管是誰？」 |
| room | 會議室細節加上排程 | 「明天有排會議的會議室裡，哪間可以視訊？」 |
| hours | 上班時段、假日 | 「王小明星期五幾點下班？」「下一個假日是哪天？」 |
| leave | 請假區間重疊、審核狀態 | 「下週有誰請假？」「誰的假還在審核？」 |
| combo | 排程結合新表 | 「營運部這週總共排了幾個班？」「明天有誰請假但還被排了班？」 |
"""

extCategories = ["org", "room", "hours", "leave", "combo"]

thisWeek = "'2026-11-16' AND '2026-11-22'"
nextWeek = "'2026-11-23' AND '2026-11-29'"
# 請假和排程一樣是時間區間，「某天有誰請假」要用區間有沒有重疊判斷，不能只看開始日期等於那天
leaveJoin = """
  FROM leave_requests l
  JOIN employees em ON em.id = l.employee_id
  JOIN resources r ON r.id = em.resource_id
"""

extCases = [
  # ── org：部門與主管（多層 JOIN、自己參照）──
  {"id": "e-org01", "category": "org", "question": "營運部有哪些員工？", "compareAsSet": True,
   "goldSql": """SELECT r.name FROM employees em
     JOIN resources r ON r.id = em.resource_id
     JOIN departments d ON d.id = em.department_id
     WHERE d.name = '營運部'"""},
  {"id": "e-org02", "category": "org", "question": "李小華的主管是誰？",
   "goldSql": """SELECT boss.name FROM employees em
     JOIN resources r ON r.id = em.resource_id
     JOIN employees mgr ON mgr.id = em.manager_id
     JOIN resources boss ON boss.id = mgr.resource_id
     WHERE r.name = '李小華'"""},
  {"id": "e-org03", "category": "org", "question": "誰是王小明的直屬部屬？", "compareAsSet": True,
   "goldSql": """SELECT r.name FROM employees em
     JOIN resources r ON r.id = em.resource_id
     JOIN employees mgr ON mgr.id = em.manager_id
     JOIN resources boss ON boss.id = mgr.resource_id
     WHERE boss.name = '王小明'"""},
  {"id": "e-org04", "category": "org", "question": "營運部隸屬於哪個部門？",
   "goldSql": "SELECT p.name FROM departments d JOIN departments p ON p.id = d.parent_id WHERE d.name = '營運部'"},
  {"id": "e-org05", "category": "org", "question": "陳大文的主管的主管是誰？",
   "goldSql": """SELECT topBoss.name FROM employees em
     JOIN resources r ON r.id = em.resource_id
     JOIN employees mgr ON mgr.id = em.manager_id
     JOIN employees mgr2 ON mgr2.id = mgr.manager_id
     JOIN resources topBoss ON topBoss.id = mgr2.resource_id
     WHERE r.name = '陳大文'"""},

  # ── room：會議室細節加上排程 ──
  {"id": "e-room01", "category": "room", "question": "容納人數超過 8 人的會議室是哪一間？",
   "goldSql": "SELECT r.name FROM rooms rm JOIN resources r ON r.id = rm.resource_id WHERE rm.capacity > 8"},
  {"id": "e-room02", "category": "room", "question": "哪間會議室沒有視訊設備？",
   "goldSql": "SELECT r.name FROM rooms rm JOIN resources r ON r.id = rm.resource_id WHERE NOT rm.has_video_conference"},
  {"id": "e-room03", "category": "room", "question": "B 會議室的容納人數是多少？",
   "goldSql": "SELECT rm.capacity FROM rooms rm JOIN resources r ON r.id = rm.resource_id WHERE r.name = 'B 會議室'"},
  {"id": "e-room04", "category": "room", "question": "有視訊設備的會議室，這週有哪些會議用到它？",
   "goldSql": f"""SELECT e.title FROM events e
     JOIN event_resources er ON er.event_id = e.id
     JOIN rooms rm ON rm.resource_id = er.resource_id
     WHERE rm.has_video_conference AND e.start_at::date BETWEEN {thisWeek}"""},
  {"id": "e-room05", "category": "room", "question": "樓層最高的會議室，下週有哪些排程？",
   "goldSql": f"""SELECT e.title FROM events e
     JOIN event_resources er ON er.event_id = e.id
     WHERE er.resource_id = (SELECT resource_id FROM rooms ORDER BY floor DESC LIMIT 1)
       AND e.start_at::date BETWEEN {nextWeek}"""},

  # ── hours：上班時段與假日 ──
  {"id": "e-hours01", "category": "hours", "question": "王小明星期三的上班時間是幾點到幾點？",
   "goldSql": """SELECT w.start_time, w.end_time FROM work_hours w
     JOIN employees em ON em.id = w.employee_id
     JOIN resources r ON r.id = em.resource_id
     WHERE r.name = '王小明' AND w.weekday = 3"""},
  {"id": "e-hours02", "category": "hours", "question": "十一月有哪些假日？",
   "goldSql": "SELECT day, name FROM holidays WHERE day BETWEEN '2026-11-01' AND '2026-11-30'"},
  {"id": "e-hours03", "category": "hours", "question": "今年還沒到的假日有哪些？",
   "goldSql": "SELECT day, name FROM holidays WHERE day > '2026-11-17' AND day <= '2026-12-31'"},
  {"id": "e-hours04", "category": "hours", "question": "王小明每週有幾天要上班？",
   "goldSql": """SELECT COUNT(*) FROM work_hours w
     JOIN employees em ON em.id = w.employee_id
     JOIN resources r ON r.id = em.resource_id
     WHERE r.name = '王小明'"""},
  {"id": "e-hours05", "category": "hours", "question": "王小明在下一個假日之前還有哪些排程？",
   "goldSql": """SELECT e.title FROM events e
     JOIN event_resources er ON er.event_id = e.id
     JOIN resources r ON r.id = er.resource_id
     WHERE r.name = '王小明' AND e.start_at > '2026-11-17 14:30'
       AND e.start_at::date < (SELECT MIN(day) FROM holidays WHERE day > '2026-11-17')"""},

  # ── leave：請假的時間區間與審核狀態 ──
  {"id": "e-leave01", "category": "leave", "question": "哪些人有請假申請還沒審核完？", "compareAsSet": True,
   "goldSql": f"SELECT r.name {leaveJoin} WHERE l.status = 'pending'"},
  {"id": "e-leave02", "category": "leave", "question": "11 月 18 日有誰請假？", "compareAsSet": True,
   "goldSql": f"""SELECT r.name {leaveJoin}
     WHERE l.status = 'approved' AND l.start_at < '2026-11-19' AND l.end_at > '2026-11-18'"""},
  {"id": "e-leave03", "category": "leave", "question": "被駁回的請假申請是誰的？", "compareAsSet": True,
   "goldSql": f"SELECT r.name {leaveJoin} WHERE l.status = 'rejected'"},
  {"id": "e-leave04", "category": "leave", "question": "核准的假裡，誰請的假跨了好幾天？", "compareAsSet": True,
   "goldSql": f"""SELECT r.name {leaveJoin}
     WHERE l.status = 'approved' AND l.end_at::date > l.start_at::date"""},
  {"id": "e-leave05", "category": "leave", "question": "11 月 26 日有誰請假？", "compareAsSet": True,
   "goldSql": f"""SELECT r.name {leaveJoin}
     WHERE l.status = 'approved' AND l.start_at < '2026-11-27' AND l.end_at > '2026-11-26'"""},

  # ── combo：排程結合新表 ──
  {"id": "e-combo01", "category": "combo", "question": "營運部的員工這週各排了幾個班？",
   "goldSql": f"""SELECT r.name, COUNT(DISTINCT e.id) FROM events e
     JOIN event_resources er ON er.event_id = e.id
     JOIN resources r ON r.id = er.resource_id
     JOIN employees em ON em.resource_id = r.id
     JOIN departments d ON d.id = em.department_id
     WHERE d.name = '營運部' AND e.category = 'shift' AND e.start_at::date BETWEEN {thisWeek}
     GROUP BY r.name"""},
  {"id": "e-combo02", "category": "combo", "question": "李小華的主管這週有什麼排程？",
   "goldSql": f"""SELECT e.title FROM events e
     JOIN event_resources er ON er.event_id = e.id
     JOIN employees boss ON boss.resource_id = er.resource_id
     WHERE boss.id = (SELECT em.manager_id FROM employees em JOIN resources r ON r.id = em.resource_id WHERE r.name = '李小華')
       AND e.start_at::date BETWEEN {thisWeek}"""},
  {"id": "e-combo03", "category": "combo", "question": "被駁回的請假申請，那段時間原本排了什麼行程？",
   "goldSql": """SELECT e.title FROM leave_requests l
     JOIN employees em ON em.id = l.employee_id
     JOIN event_resources er ON er.resource_id = em.resource_id
     JOIN events e ON e.id = er.event_id
     WHERE l.status = 'rejected' AND e.start_at < l.end_at AND e.end_at > l.start_at"""},
  {"id": "e-combo04", "category": "combo", "question": "業務部的員工有哪些排程？",
   "goldSql": """SELECT e.title FROM events e
     JOIN event_resources er ON er.event_id = e.id
     JOIN employees em ON em.resource_id = er.resource_id
     JOIN departments d ON d.id = em.department_id
     WHERE d.name = '業務部'"""},
  {"id": "e-combo05", "category": "combo", "question": "王小明在有視訊設備的會議室開過哪些會？",
   "goldSql": """SELECT e.title FROM events e
     WHERE e.id IN (SELECT er.event_id FROM event_resources er JOIN resources r ON r.id = er.resource_id WHERE r.name = '王小明')
       AND e.id IN (SELECT er.event_id FROM event_resources er JOIN rooms rm ON rm.resource_id = er.resource_id WHERE rm.has_video_conference)"""},
]
