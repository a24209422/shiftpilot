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
# 說明依工具「實際回傳什麼」寫：get_busy_periods 只有誰、起訖、種類、標題，所以假別、核准狀態、參加者與統計都要用 run_sql
jevCriteria = {
  "run_sql": "預設選項，其他選項都不適用時選這個：組織與主管、職稱、班表與假日、請假的假別與核准狀態、會議的參加者與主辦人、"
             "數量、平均與各部門統計。",
  "find_available_people": "問某段時間「誰有空」「誰沒事」「哪些人有上班」時選這個，會回傳有空的人的姓名與部門。",
  "get_busy_periods": "只在要看某個人或某個資源（會議室、設備、公務車）在某段時間「有哪些會議或請假」的時間清單時選，"
                      "只會回傳誰、開始與結束時間、種類、標題。要知道假別、核准狀態、參加者、主辦人、次數或統計，不要選這個，改選 run_sql。",
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


def buildJevRequest(question: str, now: datetime) -> dict:
  # 只送問題、日期參考與選項說明：選工具用不到資料，送得越少越少資料離開本機
  return {
    "model": getJevConfig()["model"],
    "state": f"{prompt.buildDateReference(now)}\n\n使用者的問題：{question}",
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
  except httpx.HTTPError as error:
    detail = str(error)
    response = getattr(error, "response", None)
    if response is not None:
      detail = f"HTTP {response.status_code}：{response.text[:200]}"
    # 供應商可能把送出的 key 回顯在錯誤內容裡，寫進 log 前先遮掉
    if config["apiKey"]:
      detail = detail.replace(config["apiKey"], "***")
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
