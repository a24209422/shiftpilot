"""評測題目與標準答案 SQL。

日期都以 fixture.fixedNow（2026-11-17 星期二 14:30）為準：
本週 11-16 ～ 11-22、上週 11-09 ～ 11-15、下週 11-23 ～ 11-29。

出題原則：
- 標準答案只選「回答問題最少需要的欄位」。模型多選欄位不扣分（見 scoring.resultsMatch）
- 要比對時間的題目，問法明確寫「開始時間」，避免模型回傳日期、標準答案是日期時間而被誤判
- 邊界模糊的問法（「9 點以前」含不含 9 點）改用資料裡沒有剛好落在邊界上的時間點
- compareAsSet：問「有誰」「有哪些會議室」的題目，有沒有 DISTINCT 都算對
- alsoAccept：同樣合理的其他答法。列出排程時，一場 2 個資源的會議列一次或列兩次都算對（見 listTitles）；
  但問「幾筆」「幾場」的題目只有一個正確數字，不給替代答案

標準答案查 events（一筆排程一列）或 event_details（一筆排程 × 一個資源一列），看題目問的是排程還是資源。
"""

categories = ["basic", "date", "aggregate", "type", "time", "order", "multi"]

thisWeek = "date(start_at) BETWEEN '2026-11-16' AND '2026-11-22'"
lastWeek = "date(start_at) BETWEEN '2026-11-09' AND '2026-11-15'"
nextWeek = "date(start_at) BETWEEN '2026-11-23' AND '2026-11-29'"
durationHours = "(julianday(end_at) - julianday(start_at)) * 24"


def listTitles(condition):
  """列出排程標題的題目：一筆排程列一次，或每個資源各列一次，兩種都算對。"""
  return {
    "goldSql": f"SELECT title FROM events WHERE {condition}",
    "alsoAccept": [f"SELECT title FROM event_details WHERE {condition}"],
  }


cases = [
  # ── basic：不涉及相對日期的基本篩選 ──
  {"id": "b01", "category": "basic", "question": "王小明有哪些排程？",
   "goldSql": "SELECT title FROM event_details WHERE resource_name = '王小明'"},
  {"id": "b02", "category": "basic", "question": "列出所有的會議室",
   "goldSql": "SELECT name FROM resources WHERE type = 'room'"},
  {"id": "b03", "category": "basic", "question": "列出所有週會的開始時間",
   "goldSql": "SELECT start_at FROM events WHERE title = '週會'"},
  {"id": "b04", "category": "basic", "question": "列出所有分類是 task 的排程",
   "goldSql": "SELECT title FROM events WHERE category = 'task'"},
  {"id": "b05", "category": "basic", "question": "公務車有哪些借用紀錄？",
   "goldSql": "SELECT title FROM event_details WHERE resource_name = '公務車'"},
  {"id": "b06", "category": "basic", "question": "列出林美玲所有早班的開始時間",
   "goldSql": "SELECT start_at FROM event_details WHERE resource_name = '林美玲' AND title = '早班'"},

  # ── date：今天、明天、星期幾、上週下週 ──
  {"id": "d01", "category": "date", "question": "今天有哪些排程？",
   **listTitles("date(start_at) = '2026-11-17'")},
  {"id": "d02", "category": "date", "question": "明天有哪些行程？",
   **listTitles("date(start_at) = '2026-11-18'")},
  {"id": "d03", "category": "date", "question": "後天王小明要做什麼？",
   "goldSql": "SELECT title FROM event_details WHERE resource_name = '王小明' AND date(start_at) = '2026-11-19'"},
  {"id": "d04", "category": "date", "question": "昨天誰上晚班？", "compareAsSet": True,
   "goldSql": "SELECT resource_name FROM event_details WHERE title = '晚班' AND date(start_at) = '2026-11-16'"},
  {"id": "d05", "category": "date", "question": "下週三有哪些會議？",
   **listTitles("category = 'meeting' AND date(start_at) = '2026-11-25'")},
  {"id": "d06", "category": "date", "question": "這週五陳大文有什麼行程？",
   "goldSql": "SELECT title FROM event_details WHERE resource_name = '陳大文' AND date(start_at) = '2026-11-20'"},
  {"id": "d07", "category": "date", "question": "上週有哪些排程？",
   **listTitles(lastWeek)},
  {"id": "d08", "category": "date", "question": "下週 A 會議室有哪些預約？",
   "goldSql": f"SELECT title FROM event_details WHERE resource_name = 'A 會議室' AND {nextWeek}"},
  {"id": "d09", "category": "date", "question": "11 月 26 日有哪些排程？",
   **listTitles("date(start_at) = '2026-11-26'")},
  {"id": "d10", "category": "date", "question": "這個週末有誰要上班？", "compareAsSet": True,
   "goldSql": "SELECT resource_name FROM event_details WHERE category = 'shift' "
              "AND date(start_at) BETWEEN '2026-11-21' AND '2026-11-22'"},

  # ── aggregate：COUNT、SUM、GROUP BY ──
  {"id": "a01", "category": "aggregate", "question": "總共有幾筆排程？",
   "goldSql": "SELECT COUNT(*) FROM events"},
  {"id": "a02", "category": "aggregate", "question": "這週有幾筆排班？",
   "goldSql": f"SELECT COUNT(*) FROM events WHERE category = 'shift' AND {thisWeek}"},
  {"id": "a03", "category": "aggregate", "question": "每個分類各有幾筆排程？",
   "goldSql": "SELECT category, COUNT(*) FROM events GROUP BY category"},
  {"id": "a04", "category": "aggregate", "question": "這週每個人各有幾筆排程？",
   "goldSql": "SELECT resource_name, COUNT(*) FROM event_details "
              f"WHERE resource_type = 'person' AND {thisWeek} GROUP BY resource_name"},
  {"id": "a05", "category": "aggregate", "question": "陳大文總共排了幾次晚班？",
   "goldSql": "SELECT COUNT(*) FROM event_details WHERE resource_name = '陳大文' AND title = '晚班'"},
  {"id": "a06", "category": "aggregate", "question": "A 會議室下週被預約了幾次？",
   "goldSql": f"SELECT COUNT(*) FROM event_details WHERE resource_name = 'A 會議室' AND {nextWeek}"},
  {"id": "a07", "category": "aggregate", "question": "王小明這週的會議總共幾小時？",
   "goldSql": f"SELECT SUM({durationHours}) FROM event_details "
              f"WHERE resource_name = '王小明' AND category = 'meeting' AND {thisWeek}"},
  {"id": "a08", "category": "aggregate", "question": "每個會議室各被預約了幾次？",
   "goldSql": "SELECT resource_name, COUNT(*) FROM event_details WHERE resource_type = 'room' GROUP BY resource_name"},
  {"id": "a09", "category": "aggregate", "question": "上週有幾筆排程？",
   "goldSql": f"SELECT COUNT(*) FROM events WHERE {lastWeek}"},

  # ── type：「人」「會議室」「設備」要對應到資源種類 ──
  {"id": "t01", "category": "type", "question": "列出所有員工的名字",
   "goldSql": "SELECT name FROM resources WHERE type = 'person'"},
  {"id": "t02", "category": "type", "question": "有哪些設備？",
   "goldSql": "SELECT name FROM resources WHERE type = 'equipment'"},
  {"id": "t03", "category": "type", "question": "明天有哪些會議室被使用？", "compareAsSet": True,
   "goldSql": "SELECT resource_name FROM event_details WHERE resource_type = 'room' AND date(start_at) = '2026-11-18'"},
  {"id": "t04", "category": "type", "question": "下週有哪些設備被借用？", "compareAsSet": True,
   "goldSql": f"SELECT resource_name FROM event_details WHERE resource_type = 'equipment' AND {nextWeek}"},
  {"id": "t05", "category": "type", "question": "這週有哪些人要開會？", "compareAsSet": True,
   "goldSql": "SELECT resource_name FROM event_details "
              f"WHERE resource_type = 'person' AND category = 'meeting' AND {thisWeek}"},
  {"id": "t06", "category": "type", "question": "今天有幾個人有排程？",
   "goldSql": "SELECT COUNT(DISTINCT resource_name) FROM event_details "
              "WHERE resource_type = 'person' AND date(start_at) = '2026-11-17'"},

  # ── time：一天中的時段、時長 ──
  {"id": "m01", "category": "time", "question": "明天中午 12 點以後開始的排程有哪些？",
   **listTitles("date(start_at) = '2026-11-18' AND time(start_at) >= '12:00'")},
  {"id": "m02", "category": "time", "question": "這週有哪些排程在早上 8 點半以前開始？",
   "goldSql": f"SELECT title FROM events WHERE {thisWeek} AND time(start_at) < '08:30'"},
  {"id": "m03", "category": "time", "question": "哪些排程的時間超過 5 小時？",
   "goldSql": f"SELECT title FROM events WHERE {durationHours} > 5"},
  {"id": "m04", "category": "time", "question": "今天下午 3 點半有哪些排程正在進行？",
   **listTitles("start_at <= '2026-11-17 15:30' AND end_at > '2026-11-17 15:30'")},
  {"id": "m05", "category": "time", "question": "晚上 10 點以後才結束的排程有幾筆？",
   "goldSql": "SELECT COUNT(*) FROM events WHERE time(end_at) > '22:00'"},

  # ── order：排序與 LIMIT ──
  {"id": "o01", "category": "order", "question": "王小明下一個行程是什麼？",
   "goldSql": "SELECT title FROM event_details WHERE resource_name = '王小明' AND start_at > '2026-11-17 14:30' "
              "ORDER BY start_at LIMIT 1"},
  {"id": "o02", "category": "order", "question": "最早的一筆排程是什麼？",
   "goldSql": "SELECT title FROM events ORDER BY start_at LIMIT 1"},
  {"id": "o03", "category": "order", "question": "下週誰的排程最多？",
   "goldSql": f"SELECT resource_name FROM event_details WHERE {nextWeek} "
              "GROUP BY resource_name ORDER BY COUNT(*) DESC LIMIT 1"},
  {"id": "o04", "category": "order", "question": "A 會議室最後一筆預約是什麼？",
   "goldSql": "SELECT title FROM event_details WHERE resource_name = 'A 會議室' ORDER BY start_at DESC LIMIT 1"},
  {"id": "o05", "category": "order", "question": "列出下週最早開始的三筆排程",
   "goldSql": f"SELECT title FROM events WHERE {nextWeek} ORDER BY start_at LIMIT 3"},

  # ── multi：一筆排程有多個資源 ──
  {"id": "x01", "category": "multi", "question": "設計審查有誰參加？", "compareAsSet": True,
   "goldSql": "SELECT resource_name FROM event_details WHERE title = '設計審查' AND resource_type = 'person'"},
  {"id": "x02", "category": "multi", "question": "客戶簡報在哪間會議室？", "compareAsSet": True,
   "goldSql": "SELECT resource_name FROM event_details WHERE title = '客戶簡報' AND resource_type = 'room'"},
  {"id": "x03", "category": "multi", "question": "王小明在 B 會議室開過哪些會？",
   "goldSql": "SELECT title FROM event_details WHERE resource_name = '王小明' "
              "AND event_id IN (SELECT event_id FROM event_details WHERE resource_name = 'B 會議室')"},
  {"id": "x04", "category": "multi", "question": "哪些排程有兩個以上的資源參與？",
   "goldSql": "SELECT title FROM event_details GROUP BY event_id HAVING COUNT(*) >= 2",
   "alsoAccept": ["SELECT title FROM event_details WHERE event_id IN "
                  "(SELECT event_id FROM event_details GROUP BY event_id HAVING COUNT(*) >= 2)"]},
  {"id": "x05", "category": "multi", "question": "教育訓練總共有幾個資源參與？",
   "goldSql": "SELECT COUNT(*) FROM event_details WHERE title = '教育訓練'"},
  {"id": "x06", "category": "multi", "question": "這週有幾場會議？",
   "goldSql": f"SELECT COUNT(*) FROM events WHERE category = 'meeting' AND {thisWeek}"},
]
