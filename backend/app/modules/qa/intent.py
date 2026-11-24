from dataclasses import dataclass
from datetime import datetime

import httpx

from app.modules.qa import jev

intentNames = ["query", "booking", "manageBooking", "leave"]
# previousIntent 用這個值表示上一輪是 9 個工具全給
allTools = "all"
questionName = "intent"

queryTools = ["run_sql", "find_available_people", "get_busy_periods", "find_available_resources"]

# 辦事前幾乎都要先查（找空檔、查 id），所以每組都帶齊需要的查詢工具；
# bookingId、requestId 只有 run_sql 查得到，manageBooking 與 leave 一定要有它
intentTools = {
  "query": queryTools,
  "booking": [*queryTools, "propose_booking"],
  "manageBooking": [*queryTools, "propose_reschedule_booking", "propose_cancel_booking"],
  "leave": ["run_sql", "get_busy_periods", "propose_leave", "propose_withdraw_leave"],
}

# 沿用 jev 的經驗：Jev 像在比對字詞、不理會否定句，所以每個選項只正面寫做得到的事；
# 「會議」「請假」兩邊都會出現，用「查看」與「安排、送出」這類動詞分開，辦事的動詞不放進 query
intentCriteria = {
  "query": "查看、統計或列出資料：人員、部門、主管、班表、誰有空、會議與行程、誰請假與假別狀態、會議室與設備；也包含整理重點或總結。",
  "booking": "幫使用者安排、約一場新的會議，或預約會議室、設備、公務車。",
  "manageBooking": "把已經排好的會議改到別的時間，或把它取消。",
  "leave": "替使用者自己送出請假申請，或撤回自己還沒核准的請假申請。",
}


@dataclass
class IntentDecision:
  name: str | None
  confidence: float | None
  fallbackReason: str | None
  reused: bool
  promptTokens: int | None
  seconds: float


def buildIntentRequest(question: str, now: datetime) -> dict:
  # 跟選工具一樣只送日期參考、問題與選項說明，不送對話紀錄與資料
  return {
    "model": jev.getJevConfig()["model"],
    "state": f"{jev.buildJevDateReference(now)}\n\n使用者的問題：{question}",
    "questions": {questionName: {
      "type": "choice",
      "instructions": "使用者這句話想做什麼？",
      "criteria": dict(intentCriteria),
    }},
  }


def chooseIntent(question: str, now: datetime, client: httpx.Client | None = None) -> IntentDecision:
  """永不丟例外：沒設 key 或任何失敗都回傳 name=None 與原因，讓助理 9 個工具全給。"""
  if not jev.isConfigured():
    # 助理是唯一入口，沒設 key 也要能用，所以不像 jev 模式回 503
    return IntentDecision(None, None, "not_configured", False, None, 0.0)
  decision = jev.callJev(buildIntentRequest(question, now), intentNames, questionName, client)
  return IntentDecision(decision.tool, decision.confidence, decision.fallbackReason, False, decision.promptTokens, decision.seconds)


def toolsFor(name: str | None) -> list[str] | None:
  if name is None or name == allTools:
    return None
  return intentTools[name]
