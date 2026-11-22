import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime

import httpx

from app.modules.qa import prompt

logger = logging.getLogger(__name__)

defaultUrl = "https://api.typesafe.ai/v1/systemone"
defaultModel = "jev-latest"
defaultMinConfidence = 0.5
# Jev 宣稱很快；等太久就不如直接讓 agent 三個工具都用
jevTimeout = 10
jevOptions = ["run_sql", "find_available_people", "get_busy_periods"]
questionName = "tool"

# 給 Jev 的選項說明跟 agent 給 LLM 的工具說明分開：調這裡不會改到 agent 模式的行為。
# Jev 看起來是在比對字詞、不理會「不要選這個」：所以每個選項只正面寫它答得了什麼，
# 容易混淆的字（假別、借用人、加班、沒上班）只放在答得了的 run_sql，不出現在其他選項
jevCriteria = {
  "run_sql": "查資料庫回答：人員、部門、主管與職稱；班表（上什麼班、要不要上班、誰沒有上班、加班、幾點上下班、假日與補班）；"
             "請假的假別、時數、核准或退回狀態、誰請假；會議的參加者、主辦人與場數；會議室、設備或車輛的借用人；"
             "各種數量、平均與統計。",
  "find_available_people": "在指定的一段時間裡，找出「有空」、可以找來開會或支援的人，只回傳姓名與部門。",
  "get_busy_periods": "列出某個人、某間會議室或某台設備在一段時間的行程，每筆只有名稱、開始、結束、類型與標題；"
                      "用在「那段時間有沒有事、什麼時候有事、有哪些會議」這種看行程的問題。",
}


@dataclass
class JevDecision:
  tool: str | None
  confidence: float | None
  fallbackReason: str | None
  promptTokens: int | None
  seconds: float


def getJevConfig() -> dict:
  try:
    minConfidence = float(os.getenv("JEV_MIN_CONFIDENCE", "").strip() or defaultMinConfidence)
  except ValueError:
    minConfidence = defaultMinConfidence
  return {
    # 只認 JEV_API_KEY：OpenRouter 的 Jev 是另一個端點，key 不通用，送錯地方等於把 key 給了別人
    "apiKey": os.getenv("JEV_API_KEY", "").strip(),
    "url": os.getenv("JEV_URL", "").strip() or defaultUrl,
    "model": os.getenv("JEV_MODEL", "").strip() or defaultModel,
    "minConfidence": minConfidence,
  }


def isConfigured() -> bool:
  return bool(getJevConfig()["apiKey"])


def buildJevDateReference(now: datetime) -> str:
  # 選工具用不到「下週三是幾號」；只留開頭 4 行（今天與本週、下週、上週範圍），省掉逐日表
  return "\n".join(prompt.buildDateReference(now).splitlines()[:4])


def buildJevRequest(question: str, now: datetime) -> dict:
  # 只送問題、日期參考與選項說明：選工具用不到資料，送得越少越少資料離開本機
  return {
    "model": getJevConfig()["model"],
    "state": f"{buildJevDateReference(now)}\n\n使用者的問題：{question}",
    "questions": {questionName: {
      "type": "choice",
      "instructions": "這題該用哪個工具回答？",
      "criteria": dict(jevCriteria),
    }},
  }


def parseJevResponse(payload) -> tuple[str, float, int | None]:
  # Jev 的回應格式還在變動（文件警告沒有預告期），所以只有這個函式知道欄位在哪裡
  answer = payload["answers"][questionName]
  probabilities = answer["probabilities"]
  if not isinstance(probabilities, dict) or not probabilities:
    raise ValueError("沒有機率")
  for name, value in probabilities.items():
    if name not in jevOptions:
      raise ValueError(f"不認得的選項：{name}")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
      raise ValueError(f"機率不是 0～1 的數字：{name}")
  tool = max(probabilities, key=probabilities.get)
  tokens = payload.get("usage", {}).get("input_tokens")
  return tool, float(probabilities[tool]), tokens if isinstance(tokens, int) and not isinstance(tokens, bool) else None


def chooseTool(question: str, now: datetime, client: httpx.Client | None = None) -> JevDecision:
  """永不丟例外：任何失敗都回傳 tool=None 與原因，讓問答退回三個工具都給的 agent。"""
  config = getJevConfig()
  startedAt = time.perf_counter()

  def fallback(reason: str, confidence=None, tokens=None) -> JevDecision:
    return JevDecision(None, confidence, reason, tokens, round(time.perf_counter() - startedAt, 3))

  ownClient = client is None
  client = client or httpx.Client()
  try:
    response = client.post(
      config["url"], headers={"Authorization": f"Bearer {config['apiKey']}"},
      json=buildJevRequest(question, now), timeout=jevTimeout,
    )
    response.raise_for_status()
    tool, confidence, tokens = parseJevResponse(response.json())
  # InvalidURL 不是 HTTPError 的子類別：JEV_URL 寫壞時也要退回，不能讓每個請求都變 500
  except (httpx.HTTPError, httpx.InvalidURL) as error:
    detail = str(error)
    response = getattr(error, "response", None)
    if response is not None:
      detail = response.text
    # 供應商可能把送出的 key 回顯在錯誤內容裡；先遮再截斷，否則 key 跨過截斷點時會留下半截明文
    if config["apiKey"]:
      detail = detail.replace(config["apiKey"], "***")
    if response is not None:
      detail = f"HTTP {response.status_code}：{detail[:200]}"
    logger.warning("Jev 呼叫失敗：%s", detail)
    return fallback("unavailable")
  except (ValueError, KeyError, TypeError, AttributeError):
    logger.warning("Jev 回應格式不正確")
    return fallback("bad_response")
  finally:
    if ownClient:
      client.close()
  if confidence < config["minConfidence"]:
    return fallback("low_confidence", confidence, tokens)
  return JevDecision(tool, confidence, None, tokens, round(time.perf_counter() - startedAt, 3))
