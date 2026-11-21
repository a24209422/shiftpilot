"""test 評測題目（25 題）。主 session 不打開這個檔案；調 prompt 只看 dev（cases.py）。

格式、日期基準與出題原則同 cases.py 檔頭的說明。
"""

cases = [
  # ── 組織 org ──
  {
    "id": "h-o01",
    "category": "org",
    "asker": "employee",
    "question": "王建國底下帶了哪些人？",
    "goldSql": (
      "SELECT e.name FROM employees e JOIN employees m ON m.id = e.manager_id "
      "WHERE m.name = '王建國'"
    ),
    "compareAsSet": True,
  },
  {
    "id": "h-o02",
    "category": "org",
    "asker": "requester",
    "question": "業務部資歷最老的是哪一位？",
    # 「資歷最老」指最早到職；業務部三人的到職日都不同，不會並列
    "goldSql": (
      "SELECT e.name FROM employees e JOIN departments d ON d.id = e.department_id "
      "WHERE d.name = '業務部' ORDER BY e.hired_on LIMIT 1"
    ),
  },
  {
    "id": "h-o03",
    "category": "org",
    "asker": "hr",
    "question": "進公司還不到三年的同事有誰？",
    # 以今天 2026-11-17 往回推三年；最接近邊界的人也差了好幾個月，算法不同也不影響答案
    "goldSql": "SELECT name FROM employees WHERE hired_on > DATE '2026-11-17' - INTERVAL '3 years'",
    "compareAsSet": True,
  },
  # ── 班表 shift ──
  {
    "id": "h-s01",
    "category": "shift",
    "asker": "employee",
    "question": "李佳穎這週六要上幾點到幾點的班？",
    "goldSql": (
      "SELECT d.start_at, d.end_at FROM day_shifts d JOIN employees e ON e.id = d.employee_id "
      "WHERE e.name = '李佳穎' AND d.day = '2026-11-21'"
    ),
    # 只回時刻（不帶日期）也回答了「幾點到幾點」
    "alsoAccept": [
      "SELECT d.start_at::time, d.end_at::time FROM day_shifts d JOIN employees e ON e.id = d.employee_id "
      "WHERE e.name = '李佳穎' AND d.day = '2026-11-21'",
    ],
  },
  {
    "id": "h-s02",
    "category": "shift",
    "asker": "requester",
    "question": "吳宗翰下禮拜哪天要上早班？",
    "goldSql": (
      "SELECT d.day FROM day_shifts d JOIN employees e ON e.id = d.employee_id "
      "WHERE e.name = '吳宗翰' AND d.day BETWEEN '2026-11-23' AND '2026-11-29' AND d.shift_name = '早班'"
    ),
  },
  {
    "id": "h-s03",
    "category": "shift",
    "asker": "employee",
    "question": "下禮拜一工程部有哪些人是上晚上的班？晚班、大夜都算。",
    "goldSql": (
      "SELECT e.name FROM day_shifts d JOIN employees e ON e.id = d.employee_id "
      "JOIN departments dp ON dp.id = e.department_id "
      "WHERE dp.name = '工程部' AND d.day = '2026-11-23' AND d.shift_name IN ('晚班', '大夜班')"
    ),
    "compareAsSet": True,
  },
  {
    "id": "h-s04",
    "category": "shift",
    "asker": "employee",
    "question": "黃志強上禮拜總共排了幾天班？",
    "goldSql": (
      "SELECT COUNT(*) FROM day_shifts d JOIN employees e ON e.id = d.employee_id "
      "WHERE e.name = '黃志強' AND d.day BETWEEN '2026-11-09' AND '2026-11-15' AND d.shift_name IS NOT NULL"
    ),
  },
  {
    "id": "h-s05",
    "category": "shift",
    "asker": "requester",
    "question": "這週四晚上十點半，還有誰在班上？",
    # 用十點半而不是整點：避開大夜班 22:00 開始的邊界；前一天的大夜班 07:00 就下班，不會被算進來
    "goldSql": (
      "SELECT e.name FROM day_shifts d JOIN employees e ON e.id = d.employee_id "
      "WHERE d.start_at <= '2026-11-19 22:30' AND d.end_at > '2026-11-19 22:30'"
    ),
    "compareAsSet": True,
  },
  # ── 誰有空 avail ──
  {
    "id": "h-a01",
    "category": "avail",
    "asker": "employee",
    "question": "後天早上九點到十點，業務部誰已經被占用了？在忙什麼？",
    # 反過來問「誰在忙」：要找的是重疊的忙碌時段本身，套「誰有空」的寫法答不出來
    "goldSql": (
      "SELECT e.name, b.label FROM busy_periods b JOIN employees e ON e.id = b.employee_id "
      "JOIN departments dp ON dp.id = e.department_id "
      "WHERE dp.name = '業務部' AND b.start_at < '2026-11-19 10:00' AND b.end_at > '2026-11-19 09:00'"
    ),
    "compareAsSet": True,
  },
  {
    "id": "h-a02",
    "category": "avail",
    "asker": "requester",
    "question": "11/24 下午三點到四點，工程部有誰抽得出時間？",
    "goldSql": (
      "SELECT e.name FROM employees e JOIN departments dp ON dp.id = e.department_id "
      "JOIN day_shifts d ON d.employee_id = e.id "
      "WHERE dp.name = '工程部' AND d.start_at <= '2026-11-24 15:00' AND d.end_at >= '2026-11-24 16:00' "
      "AND NOT EXISTS (SELECT 1 FROM busy_periods b WHERE b.employee_id = e.id "
      "AND b.start_at < '2026-11-24 16:00' AND b.end_at > '2026-11-24 15:00')"
    ),
    "compareAsSet": True,
    # 林小美那段假還沒核准：認為「還沒准就不算請假」也說得通，所以接受不排除待核准請假的答案
    "alsoAccept": [
      "SELECT e.name FROM employees e JOIN departments dp ON dp.id = e.department_id "
      "JOIN day_shifts d ON d.employee_id = e.id "
      "WHERE dp.name = '工程部' AND d.start_at <= '2026-11-24 15:00' AND d.end_at >= '2026-11-24 16:00' "
      "AND NOT EXISTS (SELECT 1 FROM busy_periods b WHERE b.employee_id = e.id AND b.label <> '請假（待核准）' "
      "AND b.start_at < '2026-11-24 16:00' AND b.end_at > '2026-11-24 15:00')",
    ],
  },
  {
    "id": "h-a03",
    "category": "avail",
    "asker": "manager",
    "question": "林小美下禮拜哪幾天上班時完全沒有會議、也沒請假？",
    # 只算有排班的日子：週五是公司假日，沒上班就不算「上班時沒事」
    "goldSql": (
      "SELECT d.day FROM day_shifts d JOIN employees e ON e.id = d.employee_id "
      "WHERE e.name = '林小美' AND d.day BETWEEN '2026-11-23' AND '2026-11-29' AND d.shift_name IS NOT NULL "
      "AND NOT EXISTS (SELECT 1 FROM busy_periods b WHERE b.employee_id = e.id "
      "AND b.start_at < d.end_at AND b.end_at > d.start_at)"
    ),
    "compareAsSet": True,
  },
  {
    "id": "h-a04",
    "category": "avail",
    "asker": "employee",
    "question": "張雅婷下禮拜有哪幾段時間已經被排走了？給我開始跟結束時間。",
    "goldSql": (
      "SELECT b.start_at, b.end_at FROM busy_periods b JOIN employees e ON e.id = b.employee_id "
      "WHERE e.name = '張雅婷' AND b.start_at >= '2026-11-23' AND b.start_at < '2026-11-30'"
    ),
    "compareAsSet": True,
  },
  # ── 請假 leave ──
  {
    "id": "h-l01",
    "category": "leave",
    "asker": "employee",
    "question": "林小美 11/26 開始的那段假，請的是什麼假？",
    # 一般員工看不到別人的假別：標準答案是 NULL，模型要照實查，不能自己猜
    "goldSql": (
      "SELECT l.leave_type FROM leave_requests l JOIN employees e ON e.id = l.employee_id "
      "WHERE e.name = '林小美' AND l.start_at::date = '2026-11-26'"
    ),
  },
  {
    "id": "h-l02",
    "category": "leave",
    "asker": "manager",
    "question": "劉怡君 11 月份的請假，各是什麼假、幾個小時？",
    # 主管看得到直屬部屬的假別；換成一般員工問，假別就會是 NULL
    "goldSql": (
      "SELECT l.leave_type, l.hours FROM leave_requests l JOIN employees e ON e.id = l.employee_id "
      "WHERE e.name = '劉怡君' AND l.start_at >= '2026-11-01' AND l.start_at < '2026-12-01' AND l.status = 'approved'"
    ),
  },
  {
    "id": "h-l03",
    "category": "leave",
    "asker": "requester",
    "question": "上禮拜有哪些同事請過假？",
    # 提問者自己在上週有一筆已撤回的假，撤回不算請過假
    "goldSql": (
      "SELECT e.name FROM leave_requests l JOIN employees e ON e.id = l.employee_id "
      "WHERE l.status = 'approved' AND l.start_at < '2026-11-16' AND l.end_at > '2026-11-09'"
    ),
    "compareAsSet": True,
  },
  {
    "id": "h-l04",
    "category": "leave",
    "asker": "employee",
    "question": "現在還有誰的假單卡在等主管批？",
    "goldSql": (
      "SELECT e.name FROM leave_requests l JOIN employees e ON e.id = l.employee_id "
      "WHERE l.status = 'pending'"
    ),
    "compareAsSet": True,
  },
  {
    "id": "h-l05",
    "category": "leave",
    "asker": "hr",
    "question": "吳宗翰被打回票的那張假單，原本是要請哪一天？",
    "goldSql": (
      "SELECT l.start_at::date FROM leave_requests l JOIN employees e ON e.id = l.employee_id "
      "WHERE e.name = '吳宗翰' AND l.status = 'rejected'"
    ),
    # 回開始時間（含時分）也是回答了「哪一天」
    "alsoAccept": [
      "SELECT l.start_at FROM leave_requests l JOIN employees e ON e.id = l.employee_id "
      "WHERE e.name = '吳宗翰' AND l.status = 'rejected'",
    ],
  },
  # ── 會議與資源 meet ──
  {
    "id": "h-m01",
    "category": "meet",
    "asker": "employee",
    "question": "這禮拜接下來還有哪些會要借投影機？",
    "goldSql": (
      "SELECT b.title FROM bookings b JOIN booking_resources br ON br.booking_id = b.id "
      "JOIN resources r ON r.id = br.resource_id "
      "WHERE r.name = '投影機' AND b.start_at >= '2026-11-17 14:30' AND b.start_at < '2026-11-23'"
    ),
    "compareAsSet": True,
  },
  {
    "id": "h-m02",
    "category": "meet",
    "asker": "requester",
    "question": "陳大文下禮拜要開幾場會？他自己主持的也算。",
    "goldSql": (
      "SELECT COUNT(*) FROM bookings b JOIN booking_participants p ON p.booking_id = b.id "
      "JOIN employees e ON e.id = p.employee_id "
      "WHERE e.name = '陳大文' AND b.start_at >= '2026-11-23' AND b.start_at < '2026-11-30'"
    ),
  },
  {
    "id": "h-m03",
    "category": "meet",
    "asker": "requester",
    "question": "A 會議室整個 11 月，連還沒到的也算，一共有幾場預約？",
    "goldSql": (
      "SELECT COUNT(*) FROM bookings b JOIN booking_resources br ON br.booking_id = b.id "
      "JOIN resources r ON r.id = br.resource_id "
      "WHERE r.name = 'A 會議室' AND b.start_at >= '2026-11-01' AND b.start_at < '2026-12-01'"
    ),
  },
  {
    "id": "h-m04",
    "category": "meet",
    "asker": "employee",
    "question": "新人訓練有哪些人要參加？",
    "goldSql": (
      "SELECT e.name FROM bookings b JOIN booking_participants p ON p.booking_id = b.id "
      "JOIN employees e ON e.id = p.employee_id WHERE b.title = '新人訓練'"
    ),
    "compareAsSet": True,
    # 「參加」也可以理解成不含主辦人
    "alsoAccept": [
      "SELECT e.name FROM bookings b JOIN booking_participants p ON p.booking_id = b.id "
      "JOIN employees e ON e.id = p.employee_id WHERE b.title = '新人訓練' AND p.role = 'attendee'",
    ],
  },
  # ── 統計 agg ──
  {
    "id": "h-g01",
    "category": "agg",
    "asker": "hr",
    "question": "11 月有請假的人，各自核准下來的時數加起來是多少？",
    "goldSql": (
      "SELECT e.name, SUM(l.hours) FROM leave_requests l JOIN employees e ON e.id = l.employee_id "
      "WHERE l.status = 'approved' AND l.start_at >= '2026-11-01' AND l.start_at < '2026-12-01' "
      "GROUP BY e.name"
    ),
  },
  {
    "id": "h-g02",
    "category": "agg",
    "asker": "employee",
    "question": "全公司這禮拜每天各排了幾個行程？會議、外出都算，沒有行程的日子不用列。",
    # 需求訪談同時用了兩個資源，按排程計數才不會多算一筆
    "goldSql": (
      "SELECT start_at::date, COUNT(*) FROM bookings "
      "WHERE start_at >= '2026-11-16' AND start_at < '2026-11-23' GROUP BY start_at::date"
    ),
  },
  {
    "id": "h-g03",
    "category": "agg",
    "asker": "requester",
    "question": "排程裡誰參加的會最多？自己主辦的也算。",
    # 含主辦時第一名唯一；只算 attendee 會有並列，所以題目明講主辦也算
    "goldSql": (
      "SELECT e.name FROM booking_participants p JOIN employees e ON e.id = p.employee_id "
      "GROUP BY e.name ORDER BY COUNT(*) DESC LIMIT 1"
    ),
  },
  {
    "id": "h-g04",
    "category": "agg",
    "asker": "manager",
    "question": "上個月工程部每個人各排了幾天班？",
    "goldSql": (
      "SELECT e.name, COUNT(*) FROM day_shifts d JOIN employees e ON e.id = d.employee_id "
      "JOIN departments dp ON dp.id = e.department_id "
      "WHERE dp.name = '工程部' AND d.day BETWEEN '2026-10-01' AND '2026-10-31' AND d.shift_name IS NOT NULL "
      "GROUP BY e.name"
    ),
  },
]
