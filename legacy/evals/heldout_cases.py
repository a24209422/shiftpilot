"""test 集：調 prompt 時不看的題目，用來確認改進不是只對 dev（cases.py）有效。

規則：
- 2026-11-18 在改 prompt 之前寫好並凍結。之後不再修改題目或標準答案，改了就不算沒看過的題目
- 出題的人也是調 prompt 的人，已經知道 dev 上的錯誤模式。為了不刻意出好答或難答的題目，各類別題數照 dev 的比例縮小，
  命中已知錯誤模式（時長、「現在」、多資源）的題目比例也跟 dev 差不多
- 用同一份 fixture，但換問法、換人名、換日期，不和 dev 的題目重複
- 出題原則與 cases.py 相同（最少欄位、時間題寫明「開始時間」、避開邊界、compareAsSet、alsoAccept）
- 執行 python -m evals.run --split test 只會印出分數，不印每題的 SQL
"""
from evals.cases import durationHours, lastWeek, listTitles, nextWeek, thisWeek

heldoutCases = [
  # ── basic ──
  {"id": "hb01", "category": "basic", "question": "列出李小華所有的排班",
   "goldSql": "SELECT title FROM event_details WHERE resource_name = '李小華' AND category = 'shift'"},
  {"id": "hb02", "category": "basic", "question": "陳大文的一對一面談開始時間是什麼時候？",
   "goldSql": "SELECT start_at FROM event_details WHERE resource_name = '陳大文' AND title = '一對一面談'"},
  {"id": "hb03", "category": "basic", "question": "B 會議室有哪些預約？",
   "goldSql": "SELECT title FROM event_details WHERE resource_name = 'B 會議室'"},

  # ── date ──
  {"id": "hd01", "category": "date", "question": "下週一有什麼安排？",
   **listTitles("start_at::date = '2026-11-23'")},
  {"id": "hd02", "category": "date", "question": "上週四林美玲做了什麼？",
   "goldSql": "SELECT title FROM event_details WHERE resource_name = '林美玲' AND start_at::date = '2026-11-12'"},
  # 日期參考只標到「後天」，大後天要模型自己往後數
  {"id": "hd03", "category": "date", "question": "大後天有哪些排程？",
   **listTitles("start_at::date = '2026-11-20'")},
  {"id": "hd04", "category": "date", "question": "下週有哪些人要上晚班？", "compareAsSet": True,
   "goldSql": f"SELECT resource_name FROM event_details WHERE title = '晚班' AND {nextWeek}"},
  {"id": "hd05", "category": "date", "question": "11/26 李小華要做什麼？",
   "goldSql": "SELECT title FROM event_details WHERE resource_name = '李小華' AND start_at::date = '2026-11-26'"},

  # ── aggregate ──
  {"id": "ha01", "category": "aggregate", "question": "投影機總共被借了幾次？",
   "goldSql": "SELECT COUNT(*) FROM event_details WHERE resource_name = '投影機'"},
  {"id": "ha02", "category": "aggregate", "question": "下週每個人各排了幾個班？",
   "goldSql": f"SELECT resource_name, COUNT(*) FROM event_details WHERE category = 'shift' AND {nextWeek} "
              "GROUP BY resource_name"},
  {"id": "ha03", "category": "aggregate", "question": "這週總共排了幾小時的班？",
   "goldSql": f"SELECT SUM({durationHours}) FROM events WHERE category = 'shift' AND {thisWeek}"},
  {"id": "ha04", "category": "aggregate", "question": "每種資源各有幾個？",
   "goldSql": "SELECT type, COUNT(*) FROM resources GROUP BY type"},

  # ── type ──
  {"id": "ht01", "category": "type", "question": "上週有哪些員工排了班？", "compareAsSet": True,
   "goldSql": "SELECT resource_name FROM event_details "
              f"WHERE resource_type = 'person' AND category = 'shift' AND {lastWeek}"},
  {"id": "ht02", "category": "type", "question": "公司有幾台設備？",
   "goldSql": "SELECT COUNT(*) FROM resources WHERE type = 'equipment'"},
  {"id": "ht03", "category": "type", "question": "明天有哪些人有排程？", "compareAsSet": True,
   "goldSql": "SELECT resource_name FROM event_details WHERE resource_type = 'person' AND start_at::date = '2026-11-18'"},

  # ── time ──
  # 下週沒有剛好 14:00 開始的排程，「以後」含不含 2 點都不影響答案
  {"id": "hm01", "category": "time", "question": "下週有哪些排程在下午 2 點以後開始？",
   **listTitles(f"{nextWeek} AND start_at::time >= '14:00'")},
  {"id": "hm02", "category": "time", "question": "這週有哪些排程在下午 5 點以後才結束？",
   **listTitles(f"{thisWeek} AND end_at::time > '17:00'")},
  # 後天有排程的人是王小明、林美玲、李小華，但 10 點時李小華的晚班還沒開始：只列出當天所有人的 SQL 會答錯
  {"id": "hm03", "category": "time", "question": "後天早上 10 點有誰在忙？", "compareAsSet": True,
   "goldSql": "SELECT resource_name FROM event_details WHERE resource_type = 'person' "
              "AND start_at <= '2026-11-19 10:00' AND end_at > '2026-11-19 10:00'"},

  # ── order ──
  # 「現在」是 11-17 14:30，陳大文當天 16:00 的晚班還沒開始，上一次是 11-16
  {"id": "ho01", "category": "order", "question": "陳大文上一次晚班的開始時間是？",
   "goldSql": "SELECT start_at FROM event_details WHERE resource_name = '陳大文' AND title = '晚班' "
              "AND start_at < '2026-11-17 14:30' ORDER BY start_at DESC LIMIT 1"},
  {"id": "ho02", "category": "order", "question": "這週誰的排班最多？",
   "goldSql": f"SELECT resource_name FROM event_details WHERE category = 'shift' AND {thisWeek} "
              "GROUP BY resource_name ORDER BY COUNT(*) DESC LIMIT 1"},
  {"id": "ho03", "category": "order", "question": "這週最後兩筆排程是什麼？",
   "goldSql": f"SELECT title FROM events WHERE {thisWeek} ORDER BY start_at DESC LIMIT 2"},

  # ── multi ──
  # 問題沒說「會議室」，模型要自己判斷「在哪裡」指的是 room
  {"id": "hx01", "category": "multi", "question": "產品 demo 在哪裡開？", "compareAsSet": True,
   "goldSql": "SELECT resource_name FROM event_details WHERE title = '產品 demo' AND resource_type = 'room'"},
  {"id": "hx02", "category": "multi", "question": "王小明開會最常用哪間會議室？",
   "goldSql": "SELECT resource_name FROM event_details WHERE resource_type = 'room' "
              "AND event_id IN (SELECT event_id FROM event_details WHERE resource_name = '王小明') "
              "GROUP BY resource_name ORDER BY COUNT(*) DESC LIMIT 1"},
  # 上週的需求訪談有 2 個資源：用 COUNT(*) 查 event_details 會得到 3
  {"id": "hx03", "category": "multi", "question": "上週開了幾次會？",
   "goldSql": f"SELECT COUNT(*) FROM events WHERE category = 'meeting' AND {lastWeek}"},
]
