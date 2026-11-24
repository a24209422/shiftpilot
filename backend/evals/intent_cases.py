"""意圖評測的辦事題，只有 dev。

查詢題直接沿用 cases.py 的 dev 40 題（全部是查詢）。
每個意圖 8 題：至少 2 題直接下指令、2 題先問再辦、2 題口語；不照抄 cases.py 的句子。
"""

actionCases = [
  # booking：預約新會議或資源
  {"id": "ib01", "intent": "booking", "question": "幫我跟黃志強約明天下午三點的會議，一小時"},
  {"id": "ib02", "intent": "booking", "question": "預約下週一上午十點的 A 會議室，開專案討論會"},
  {"id": "ib03", "intent": "booking", "question": "下週二下午誰有空？有空的話幫我約他們開會"},
  {"id": "ib04", "intent": "booking", "question": "明天下午 B 會議室有空嗎？有的話幫我訂兩點到三點"},
  {"id": "ib05", "intent": "booking", "question": "想找林小美聊一下下週的進度，排個半小時"},
  {"id": "ib06", "intent": "booking", "question": "跟業務部的人喬個時間開會"},
  {"id": "ib07", "intent": "booking", "question": "我要借公務車，下週三整天"},
  {"id": "ib08", "intent": "booking", "question": "這週五下午幫我開一個部門會議，找一間坐得下十個人的會議室"},
  # manageBooking：改期或取消既有會議（改期 4 題、取消 4 題）
  {"id": "im01", "intent": "manageBooking", "question": "把明天的週會改到下午四點"},
  {"id": "im02", "intent": "manageBooking", "question": "取消我下週一的專案討論會"},
  {"id": "im03", "intent": "manageBooking", "question": "季度檢討延後一個小時"},
  {"id": "im04", "intent": "manageBooking", "question": "我明天有哪些會？把下午那場取消"},
  {"id": "im05", "intent": "manageBooking", "question": "下週二的會可以挪到週三同一時間嗎"},
  {"id": "im06", "intent": "manageBooking", "question": "專案啟動會不開了，幫我取消"},
  {"id": "im07", "intent": "manageBooking", "question": "林小美說她週四沒空，把我們週四的會改到週五"},
  {"id": "im08", "intent": "manageBooking", "question": "查一下我這週主辦的會，把最後一場取消"},
  # leave：請假或撤回（請假 5 題、撤回 3 題）
  {"id": "il01", "intent": "leave", "question": "幫我請下週三一整天的特休"},
  {"id": "il02", "intent": "leave", "question": "我明天下午要請病假"},
  {"id": "il03", "intent": "leave", "question": "下週五我有沒有會議？沒有的話幫我請一天事假"},
  {"id": "il04", "intent": "leave", "question": "撤回我上週送的那筆特休申請"},
  {"id": "il05", "intent": "leave", "question": "我還有幾小時特休？夠的話幫我請下週一"},
  {"id": "il06", "intent": "leave", "question": "那張假單我不請了，幫我抽回來"},
  {"id": "il07", "intent": "leave", "question": "身體不太舒服，今天下午想先走"},
  {"id": "il08", "intent": "leave", "question": "剛剛送的請假先收回"},
]
