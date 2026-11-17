"""評測題目與標準答案 SQL。

日期都以 fixture.fixedNow（2026-11-17 星期二 14:30）為準：
本週 11-16 ～ 11-22、上週 11-09 ～ 11-15、下週 11-23 ～ 11-29。

出題原則：
- 標準答案只選「回答問題最少需要的欄位」。模型多選欄位不扣分（見 scoring.resultsMatch）
- 要比對時間的題目，問法明確寫「開始時間」，避免模型回傳日期、標準答案是日期時間而被誤判
- 邊界模糊的問法（「9 點以前」含不含 9 點）改用資料裡沒有剛好落在邊界上的時間點
- compareAsSet：問「有誰」「有哪些會議室」的題目，有沒有 DISTINCT 都算對
"""

categories = ["basic", "date", "aggregate", "type", "time", "order"]

eventJoin = "FROM events e JOIN resources r ON e.resource_id = r.id"
thisWeek = "date(e.start_at) BETWEEN '2026-11-16' AND '2026-11-22'"
lastWeek = "date(e.start_at) BETWEEN '2026-11-09' AND '2026-11-15'"
nextWeek = "date(e.start_at) BETWEEN '2026-11-23' AND '2026-11-29'"
durationHours = "(julianday(e.end_at) - julianday(e.start_at)) * 24"

cases = [
  # ── basic：不涉及相對日期的基本篩選 ──
  {"id": "b01", "category": "basic", "question": "王小明有哪些排程？",
   "goldSql": f"SELECT e.title {eventJoin} WHERE r.name = '王小明'"},
  {"id": "b02", "category": "basic", "question": "列出所有的會議室",
   "goldSql": "SELECT name FROM resources WHERE type = 'room'"},
  {"id": "b03", "category": "basic", "question": "列出所有週會的開始時間",
   "goldSql": "SELECT e.start_at FROM events e WHERE e.title = '週會'"},
  {"id": "b04", "category": "basic", "question": "列出所有分類是 task 的排程",
   "goldSql": "SELECT e.title FROM events e WHERE e.category = 'task'"},
  {"id": "b05", "category": "basic", "question": "公務車有哪些借用紀錄？",
   "goldSql": f"SELECT e.title {eventJoin} WHERE r.name = '公務車'"},
  {"id": "b06", "category": "basic", "question": "列出林美玲所有早班的開始時間",
   "goldSql": f"SELECT e.start_at {eventJoin} WHERE r.name = '林美玲' AND e.title = '早班'"},

  # ── date：今天、明天、星期幾、上週下週 ──
  {"id": "d01", "category": "date", "question": "今天有哪些排程？",
   "goldSql": "SELECT e.title FROM events e WHERE date(e.start_at) = '2026-11-17'"},
  {"id": "d02", "category": "date", "question": "明天有哪些行程？",
   "goldSql": "SELECT e.title FROM events e WHERE date(e.start_at) = '2026-11-18'"},
  {"id": "d03", "category": "date", "question": "後天王小明要做什麼？",
   "goldSql": f"SELECT e.title {eventJoin} WHERE r.name = '王小明' AND date(e.start_at) = '2026-11-19'"},
  {"id": "d04", "category": "date", "question": "昨天誰上晚班？", "compareAsSet": True,
   "goldSql": f"SELECT r.name {eventJoin} WHERE e.title = '晚班' AND date(e.start_at) = '2026-11-16'"},
  {"id": "d05", "category": "date", "question": "下週三有哪些會議？",
   "goldSql": "SELECT e.title FROM events e WHERE e.category = 'meeting' AND date(e.start_at) = '2026-11-25'"},
  {"id": "d06", "category": "date", "question": "這週五陳大文有什麼行程？",
   "goldSql": f"SELECT e.title {eventJoin} WHERE r.name = '陳大文' AND date(e.start_at) = '2026-11-20'"},
  {"id": "d07", "category": "date", "question": "上週有哪些排程？",
   "goldSql": f"SELECT e.title FROM events e WHERE {lastWeek}"},
  {"id": "d08", "category": "date", "question": "下週 A 會議室有哪些預約？",
   "goldSql": f"SELECT e.title {eventJoin} WHERE r.name = 'A 會議室' AND {nextWeek}"},
  {"id": "d09", "category": "date", "question": "11 月 26 日有哪些排程？",
   "goldSql": "SELECT e.title FROM events e WHERE date(e.start_at) = '2026-11-26'"},
  {"id": "d10", "category": "date", "question": "這個週末有誰要上班？", "compareAsSet": True,
   "goldSql": f"SELECT r.name {eventJoin} WHERE e.category = 'shift' "
              "AND date(e.start_at) BETWEEN '2026-11-21' AND '2026-11-22'"},

  # ── aggregate：COUNT、SUM、GROUP BY ──
  {"id": "a01", "category": "aggregate", "question": "總共有幾筆排程？",
   "goldSql": "SELECT COUNT(*) FROM events"},
  {"id": "a02", "category": "aggregate", "question": "這週有幾筆排班？",
   "goldSql": f"SELECT COUNT(*) FROM events e WHERE e.category = 'shift' AND {thisWeek}"},
  {"id": "a03", "category": "aggregate", "question": "每個分類各有幾筆排程？",
   "goldSql": "SELECT category, COUNT(*) FROM events GROUP BY category"},
  {"id": "a04", "category": "aggregate", "question": "這週每個人各有幾筆排程？",
   "goldSql": f"SELECT r.name, COUNT(*) {eventJoin} WHERE r.type = 'person' AND {thisWeek} GROUP BY r.name"},
  {"id": "a05", "category": "aggregate", "question": "陳大文總共排了幾次晚班？",
   "goldSql": f"SELECT COUNT(*) {eventJoin} WHERE r.name = '陳大文' AND e.title = '晚班'"},
  {"id": "a06", "category": "aggregate", "question": "A 會議室下週被預約了幾次？",
   "goldSql": f"SELECT COUNT(*) {eventJoin} WHERE r.name = 'A 會議室' AND {nextWeek}"},
  {"id": "a07", "category": "aggregate", "question": "王小明這週的會議總共幾小時？",
   "goldSql": f"SELECT SUM({durationHours}) {eventJoin} "
              f"WHERE r.name = '王小明' AND e.category = 'meeting' AND {thisWeek}"},
  {"id": "a08", "category": "aggregate", "question": "每個會議室各被預約了幾次？",
   "goldSql": f"SELECT r.name, COUNT(*) {eventJoin} WHERE r.type = 'room' GROUP BY r.name"},
  {"id": "a09", "category": "aggregate", "question": "上週有幾筆排程？",
   "goldSql": f"SELECT COUNT(*) FROM events e WHERE {lastWeek}"},

  # ── type：「人」「會議室」「設備」要對應到 resources.type ──
  {"id": "t01", "category": "type", "question": "列出所有員工的名字",
   "goldSql": "SELECT name FROM resources WHERE type = 'person'"},
  {"id": "t02", "category": "type", "question": "有哪些設備？",
   "goldSql": "SELECT name FROM resources WHERE type = 'equipment'"},
  {"id": "t03", "category": "type", "question": "明天有哪些會議室被使用？", "compareAsSet": True,
   "goldSql": f"SELECT r.name {eventJoin} WHERE r.type = 'room' AND date(e.start_at) = '2026-11-18'"},
  {"id": "t04", "category": "type", "question": "下週有哪些設備被借用？", "compareAsSet": True,
   "goldSql": f"SELECT r.name {eventJoin} WHERE r.type = 'equipment' AND {nextWeek}"},
  {"id": "t05", "category": "type", "question": "這週有哪些人要開會？", "compareAsSet": True,
   "goldSql": f"SELECT r.name {eventJoin} WHERE r.type = 'person' AND e.category = 'meeting' AND {thisWeek}"},
  {"id": "t06", "category": "type", "question": "今天有幾個人有排程？",
   "goldSql": f"SELECT COUNT(DISTINCT r.id) {eventJoin} WHERE r.type = 'person' AND date(e.start_at) = '2026-11-17'"},

  # ── time：一天中的時段、時長 ──
  {"id": "m01", "category": "time", "question": "明天中午 12 點以後開始的排程有哪些？",
   "goldSql": "SELECT e.title FROM events e WHERE date(e.start_at) = '2026-11-18' AND time(e.start_at) >= '12:00'"},
  {"id": "m02", "category": "time", "question": "這週有哪些排程在早上 8 點半以前開始？",
   "goldSql": f"SELECT e.title FROM events e WHERE {thisWeek} AND time(e.start_at) < '08:30'"},
  {"id": "m03", "category": "time", "question": "哪些排程的時間超過 5 小時？",
   "goldSql": f"SELECT e.title FROM events e WHERE {durationHours} > 5"},
  {"id": "m04", "category": "time", "question": "今天下午 3 點半有哪些排程正在進行？",
   "goldSql": "SELECT e.title FROM events e "
              "WHERE e.start_at <= '2026-11-17 15:30' AND e.end_at > '2026-11-17 15:30'"},
  {"id": "m05", "category": "time", "question": "晚上 10 點以後才結束的排程有幾筆？",
   "goldSql": "SELECT COUNT(*) FROM events e WHERE time(e.end_at) > '22:00'"},

  # ── order：排序與 LIMIT ──
  {"id": "o01", "category": "order", "question": "王小明下一個行程是什麼？",
   "goldSql": f"SELECT e.title {eventJoin} WHERE r.name = '王小明' AND e.start_at > '2026-11-17 14:30' "
              "ORDER BY e.start_at LIMIT 1"},
  {"id": "o02", "category": "order", "question": "最早的一筆排程是什麼？",
   "goldSql": "SELECT e.title FROM events e ORDER BY e.start_at LIMIT 1"},
  {"id": "o03", "category": "order", "question": "下週誰的排程最多？",
   "goldSql": f"SELECT r.name {eventJoin} WHERE {nextWeek} GROUP BY r.name ORDER BY COUNT(*) DESC LIMIT 1"},
  {"id": "o04", "category": "order", "question": "A 會議室最後一筆預約是什麼？",
   "goldSql": f"SELECT e.title {eventJoin} WHERE r.name = 'A 會議室' ORDER BY e.start_at DESC LIMIT 1"},
  {"id": "o05", "category": "order", "question": "列出下週最早開始的三筆排程",
   "goldSql": f"SELECT e.title FROM events e WHERE {nextWeek} ORDER BY e.start_at LIMIT 3"},
]
