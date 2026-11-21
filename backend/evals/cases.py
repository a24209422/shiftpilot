"""dev 評測題目（40 題）。調 prompt 只看這一份；test 題在 heldout_cases.py，不要打開。

日期都以 fixture.fixedNow（2026-11-17 星期二 14:30）為準：本週 11-16～11-22、上週 11-09～11-15、下週 11-23～11-29。
標準答案寫在沙盒的 10 張表上（欄位見 app/modules/qa/prompt.py 的 schemaText），在提問者自己的沙盒執行，
所以權限差異會自動反映在答案上：一般員工問別人的假別，標準答案就是 NULL。

出題原則：
- 標準答案只選回答問題最少需要的欄位；模型多選欄位不扣分
- 要比對時間時，題目寫明「開始時間」「幾點到幾點」
- 邊界模糊的問法（「9 點以前」）避開資料裡剛好落在邊界的時間
- 問「幾筆」「幾個人」只有一個正確數字，不給 alsoAccept
- compareAsSet：問「有誰」「有哪些」時 True
- 問「最多」「排名」時用 LIMIT 限定答案，不靠資料列順序
"""

categories = ["org", "shift", "avail", "leave", "meet", "agg"]

cases = [
  {
    "id": "o01", "category": "org", "asker": "employee",
    "question": "工程部有哪些人？",
    "goldSql": "SELECT e.name FROM employees e JOIN departments d ON d.id = e.department_id WHERE d.name = '工程部'",
    "compareAsSet": True,
  },
  {
    "id": "o02", "category": "org", "asker": "employee",
    "question": "林小美的主管是誰？",
    "goldSql": "SELECT m.name FROM employees e JOIN employees m ON m.id = e.manager_id WHERE e.name = '林小美'",
  },
  {
    "id": "o03", "category": "org", "asker": "employee",
    "question": "吳宗翰是哪個部門的？職稱是什麼？",
    "goldSql": (
      "SELECT d.name, e.job_title FROM employees e JOIN departments d ON d.id = e.department_id "
      "WHERE e.name = '吳宗翰'"
    ),
  },
  {
    "id": "o04", "category": "org", "asker": "manager",
    "question": "陳大文底下有哪些人？",
    "goldSql": "SELECT e.name FROM employees e JOIN employees m ON m.id = e.manager_id WHERE m.name = '陳大文'",
    "compareAsSet": True,
  },
  {
    "id": "o05", "category": "org", "asker": "employee",
    "question": "人資部有幾個人？",
    "goldSql": "SELECT count(*) FROM employees e JOIN departments d ON d.id = e.department_id WHERE d.name = '人資部'",
  },
  {
    "id": "s01", "category": "shift", "asker": "employee",
    "question": "黃志強明天上什麼班？",
    "goldSql": "SELECT s.shift_name FROM day_shifts s JOIN employees e ON e.id = s.employee_id WHERE e.name = '黃志強' AND s.day = '2026-11-18'",
  },
  {
    "id": "s02", "category": "shift", "asker": "employee",
    "question": "今天有誰上大夜班？",
    "goldSql": "SELECT e.name FROM day_shifts s JOIN employees e ON e.id = s.employee_id WHERE s.day = '2026-11-17' AND s.shift_name = '大夜班'",
    "compareAsSet": True,
  },
  {
    "id": "s03", "category": "shift", "asker": "employee",
    "question": "林小美明天要上班嗎？",
    "goldSql": "SELECT s.shift_name FROM day_shifts s JOIN employees e ON e.id = s.employee_id WHERE e.name = '林小美' AND s.day = '2026-11-18'",
  },
  {
    "id": "s04", "category": "shift", "asker": "employee",
    "question": "下週有誰上晚班？",
    "goldSql": (
      "SELECT DISTINCT e.name FROM day_shifts s JOIN employees e ON e.id = s.employee_id "
      "WHERE s.shift_name = '晚班' AND s.day BETWEEN '2026-11-23' AND '2026-11-29'"
    ),
    "compareAsSet": True,
  },
  {
    "id": "s05", "category": "shift", "asker": "employee",
    "question": "鄭家豪今天的大夜班幾點下班？",
    "goldSql": "SELECT s.end_at FROM day_shifts s JOIN employees e ON e.id = s.employee_id WHERE e.name = '鄭家豪' AND s.day = '2026-11-17'",
  },
  {
    "id": "s06", "category": "shift", "asker": "employee",
    "question": "下週五是國定假日嗎？",
    "goldSql": "SELECT kind FROM calendar_days WHERE day = '2026-11-27'",
    "alsoAccept": ["SELECT name FROM calendar_days WHERE day = '2026-11-27' AND kind = 'holiday'"],
  },
  {
    "id": "s07", "category": "shift", "asker": "employee",
    "question": "李佳穎這週六要加班嗎？幾點到幾點？",
    "goldSql": "SELECT s.start_at, s.end_at FROM day_shifts s JOIN employees e ON e.id = s.employee_id WHERE e.name = '李佳穎' AND s.day = '2026-11-21'",
  },
  {
    "id": "s08", "category": "shift", "asker": "employee",
    "question": "12 月 5 日補班那天，劉怡君上什麼班？",
    "goldSql": "SELECT s.shift_name FROM day_shifts s JOIN employees e ON e.id = s.employee_id WHERE e.name = '劉怡君' AND s.day = '2026-12-05'",
  },
  {
    "id": "a01", "category": "avail", "asker": "employee",
    "question": "下週二下午兩點到三點，工程部有誰有空？",
    "goldSql": (
      "SELECT e.name FROM employees e JOIN departments d ON d.id = e.department_id "
      "JOIN day_shifts s ON s.employee_id = e.id "
      "WHERE d.name = '工程部' AND s.start_at <= '2026-11-24 14:00' AND s.end_at >= '2026-11-24 15:00' "
      "AND NOT EXISTS (SELECT 1 FROM busy_periods b WHERE b.employee_id = e.id "
      "AND b.start_at < '2026-11-24 15:00' AND b.end_at > '2026-11-24 14:00')"
    ),
    "compareAsSet": True,
  },
  {
    "id": "a02", "category": "avail", "asker": "employee",
    "question": "現在有誰正在請假？",
    "goldSql": (
      "SELECT DISTINCT e.name FROM busy_periods b JOIN employees e ON e.id = b.employee_id "
      "WHERE b.kind = 'leave' AND b.start_at <= '2026-11-17 14:30' AND b.end_at > '2026-11-17 14:30'"
    ),
    "compareAsSet": True,
  },
  {
    "id": "a03", "category": "avail", "asker": "requester",
    "question": "林小美下週二下午有沒有會議或請假？",
    "goldSql": (
      "SELECT b.kind FROM busy_periods b JOIN employees e ON e.id = b.employee_id "
      "WHERE e.name = '林小美' AND b.start_at < '2026-11-24 18:00' AND b.end_at > '2026-11-24 12:00'"
    ),
    "alsoAccept": [
      "SELECT b.label FROM busy_periods b JOIN employees e ON e.id = b.employee_id "
      "WHERE e.name = '林小美' AND b.start_at < '2026-11-24 18:00' AND b.end_at > '2026-11-24 12:00'"
    ],
  },
  {
    "id": "a04", "category": "avail", "asker": "employee",
    "question": "下週二下午三點到四點，A 會議室有什麼會議？",
    "goldSql": (
      "SELECT b.title FROM bookings b JOIN booking_resources br ON br.booking_id = b.id "
      "JOIN resources r ON r.id = br.resource_id "
      "WHERE r.name = 'A 會議室' AND b.start_at < '2026-11-24 16:00' AND b.end_at > '2026-11-24 15:00'"
    ),
    "compareAsSet": True,
  },
  {
    "id": "a05", "category": "avail", "asker": "employee",
    "question": "李佳穎明天哪些時段有事？",
    "goldSql": (
      "SELECT b.start_at, b.end_at FROM busy_periods b JOIN employees e ON e.id = b.employee_id "
      "WHERE e.name = '李佳穎' AND b.start_at >= '2026-11-18' AND b.start_at < '2026-11-19'"
    ),
    "compareAsSet": True,
  },
  {
    "id": "a06", "category": "avail", "asker": "employee",
    "question": "下週三上午九點到十二點，哪些人沒有上班？",
    "goldSql": (
      "SELECT e.name FROM employees e WHERE NOT EXISTS (SELECT 1 FROM day_shifts s WHERE s.employee_id = e.id "
      "AND s.start_at <= '2026-11-25 09:00' AND s.end_at >= '2026-11-25 12:00')"
    ),
    "compareAsSet": True,
  },
  {
    "id": "a07", "category": "avail", "asker": "hr",
    "question": "明天下午兩點到三點，業務部有誰有空？",
    "goldSql": (
      "SELECT e.name FROM employees e JOIN departments d ON d.id = e.department_id "
      "JOIN day_shifts s ON s.employee_id = e.id "
      "WHERE d.name = '業務部' AND s.start_at <= '2026-11-18 14:00' AND s.end_at >= '2026-11-18 15:00' "
      "AND NOT EXISTS (SELECT 1 FROM busy_periods b WHERE b.employee_id = e.id "
      "AND b.start_at < '2026-11-18 15:00' AND b.end_at > '2026-11-18 14:00')"
    ),
    "compareAsSet": True,
  },
  {
    "id": "l01", "category": "leave", "asker": "employee",
    "question": "林小美這週請了什麼假？",
    "goldSql": (
      "SELECT r.leave_type FROM leave_requests r JOIN employees e ON e.id = r.employee_id "
      "WHERE e.name = '林小美' AND r.status IN ('pending', 'approved') "
      "AND r.start_at < '2026-11-23' AND r.end_at > '2026-11-16'"
    ),
  },
  {
    "id": "l02", "category": "leave", "asker": "manager",
    "question": "林小美這週請了什麼假？",
    "goldSql": (
      "SELECT r.leave_type FROM leave_requests r JOIN employees e ON e.id = r.employee_id "
      "WHERE e.name = '林小美' AND r.status IN ('pending', 'approved') "
      "AND r.start_at < '2026-11-23' AND r.end_at > '2026-11-16'"
    ),
  },
  {
    "id": "l03", "category": "leave", "asker": "employee",
    "question": "這週有誰請假？",
    "goldSql": (
      "SELECT DISTINCT e.name FROM leave_requests r JOIN employees e ON e.id = r.employee_id "
      "WHERE r.status IN ('pending', 'approved') AND r.start_at < '2026-11-23' AND r.end_at > '2026-11-16'"
    ),
    "compareAsSet": True,
  },
  {
    "id": "l04", "category": "leave", "asker": "manager",
    "question": "目前有哪些請假還在等核准？是什麼假？",
    "goldSql": (
      "SELECT e.name, r.leave_type FROM leave_requests r JOIN employees e ON e.id = r.employee_id "
      "WHERE r.status = 'pending'"
    ),
    "compareAsSet": True,
  },
  {
    "id": "l05", "category": "leave", "asker": "requester",
    "question": "林小美申請的特休總共幾小時？",
    "goldSql": (
      "SELECT sum(r.hours) FROM leave_requests r JOIN employees e ON e.id = r.employee_id "
      "WHERE e.name = '林小美' AND r.leave_type = '特休' AND r.status IN ('pending', 'approved')"
    ),
  },
  {
    "id": "l06", "category": "leave", "asker": "hr",
    "question": "有哪些人的請假申請被退回？",
    "goldSql": (
      "SELECT e.name FROM leave_requests r JOIN employees e ON e.id = r.employee_id "
      "WHERE r.status = 'rejected'"
    ),
    "compareAsSet": True,
  },
  {
    "id": "l07", "category": "leave", "asker": "requester",
    "question": "林小美有哪些已經核准的假別？",
    "goldSql": (
      "SELECT r.leave_type FROM leave_requests r JOIN employees e ON e.id = r.employee_id "
      "WHERE e.name = '林小美' AND r.status = 'approved'"
    ),
    "compareAsSet": True,
  },
  {
    "id": "l08", "category": "leave", "asker": "employee",
    "question": "吳宗翰被退回的那筆請假是什麼假別？",
    "goldSql": (
      "SELECT r.leave_type FROM leave_requests r JOIN employees e ON e.id = r.employee_id "
      "WHERE e.name = '吳宗翰' AND r.status = 'rejected'"
    ),
  },
  {
    "id": "m01", "category": "meet", "asker": "employee",
    "question": "下週三 B 會議室有哪些會議？",
    "goldSql": (
      "SELECT b.title FROM bookings b JOIN booking_resources br ON br.booking_id = b.id "
      "JOIN resources r ON r.id = br.resource_id WHERE r.name = 'B 會議室' AND b.start_at::date = '2026-11-25'"
    ),
    "compareAsSet": True,
  },
  {
    "id": "m02", "category": "meet", "asker": "requester",
    "question": "林小美下週有幾場會議？",
    "goldSql": (
      "SELECT count(DISTINCT b.id) FROM bookings b JOIN booking_participants p ON p.booking_id = b.id "
      "JOIN employees e ON e.id = p.employee_id "
      "WHERE e.name = '林小美' AND b.start_at >= '2026-11-23' AND b.start_at < '2026-11-30'"
    ),
  },
  {
    "id": "m03", "category": "meet", "asker": "employee",
    "question": "這週五有幾場會議？",
    "goldSql": "SELECT count(DISTINCT id) FROM bookings WHERE start_at::date = '2026-11-20'",
  },
  {
    "id": "m04", "category": "meet", "asker": "employee",
    "question": "公務車這週是誰借的？",
    "goldSql": (
      "SELECT DISTINCT e.name FROM bookings b JOIN booking_resources br ON br.booking_id = b.id "
      "JOIN resources r ON r.id = br.resource_id JOIN booking_participants p ON p.booking_id = b.id AND p.role = 'organizer' "
      "JOIN employees e ON e.id = p.employee_id "
      "WHERE r.name = '公務車' AND b.start_at >= '2026-11-16' AND b.start_at < '2026-11-23'"
    ),
  },
  {
    "id": "m05", "category": "meet", "asker": "employee",
    "question": "季度檢討有誰參加？",
    "goldSql": (
      "SELECT e.name FROM bookings b JOIN booking_participants p ON p.booking_id = b.id "
      "JOIN employees e ON e.id = p.employee_id WHERE b.title = '季度檢討'"
    ),
    # 有人不把主辦算進「參加」
    "alsoAccept": [
      "SELECT e.name FROM bookings b JOIN booking_participants p ON p.booking_id = b.id "
      "JOIN employees e ON e.id = p.employee_id WHERE b.title = '季度檢討' AND p.role = 'attendee'"
    ],
    "compareAsSet": True,
  },
  {
    "id": "m06", "category": "meet", "asker": "employee",
    "question": "專案啟動會幾點開始？",
    "goldSql": "SELECT start_at FROM bookings WHERE title = '專案啟動會'",
    "alsoAccept": ["SELECT start_at::time FROM bookings WHERE title = '專案啟動會'"],
  },
  {
    "id": "m07", "category": "meet", "asker": "employee",
    "question": "投影機下週什麼時候有人用？開始時間和結束時間是？",
    "goldSql": (
      "SELECT b.start_at, b.end_at FROM bookings b JOIN booking_resources br ON br.booking_id = b.id "
      "JOIN resources r ON r.id = br.resource_id "
      "WHERE r.name = '投影機' AND b.start_at >= '2026-11-23' AND b.start_at < '2026-11-30'"
    ),
  },
  {
    "id": "g01", "category": "agg", "asker": "employee",
    "question": "每個部門各有幾個人？",
    "goldSql": "SELECT d.name, count(e.id) FROM departments d LEFT JOIN employees e ON e.department_id = d.id GROUP BY d.name",
  },
  {
    "id": "g02", "category": "agg", "asker": "hr",
    "question": "這個月已核准的請假，哪個部門的總時數最多？",
    "goldSql": (
      "SELECT d.name FROM leave_requests r JOIN employees e ON e.id = r.employee_id "
      "JOIN departments d ON d.id = e.department_id "
      "WHERE r.status = 'approved' AND r.start_at >= '2026-11-01' AND r.start_at < '2026-12-01' "
      "GROUP BY d.name ORDER BY sum(r.hours) DESC LIMIT 1"
    ),
  },
  {
    "id": "g03", "category": "agg", "asker": "hr",
    "question": "各種假別已核准的總時數各是多少？",
    "goldSql": "SELECT leave_type, sum(hours) FROM leave_requests WHERE status = 'approved' GROUP BY leave_type",
    # 已離職的人不在 employees：有人會 JOIN employees 而排除他的假
    "alsoAccept": [
      "SELECT r.leave_type, sum(r.hours) FROM leave_requests r JOIN employees e ON e.id = r.employee_id "
      "WHERE r.status = 'approved' GROUP BY r.leave_type"
    ],
  },
  {
    "id": "g04", "category": "agg", "asker": "employee",
    "question": "把主辦人也算進去，每場會議平均有幾個人參加？",
    "goldSql": "SELECT count(*)::numeric / count(DISTINCT booking_id) FROM booking_participants",
  },
  {
    "id": "g05", "category": "agg", "asker": "employee",
    "question": "這週每天各有幾場會議？",
    "goldSql": (
      "SELECT start_at::date, count(*) FROM bookings "
      "WHERE start_at >= '2026-11-16' AND start_at < '2026-11-23' GROUP BY start_at::date"
    ),
    # 「會議」也可能只指分類為會議的排程（不含外出、訓練）
    "alsoAccept": [
      "SELECT start_at::date, count(*) FROM bookings "
      "WHERE category = '會議' AND start_at >= '2026-11-16' AND start_at < '2026-11-23' GROUP BY start_at::date"
    ],
  },
]
