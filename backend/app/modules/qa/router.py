from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.infra.actor import Actor
from app.infra.http import connDependency, requirePermission
from app.modules.qa import intent, jev, llm, service

router = APIRouter()
askQa = requirePermission("qa.ask")


class AskBody(BaseModel):
  question: str
  model: str
  mode: Literal["pipeline", "agent", "jev", "assistant", "assistant-jev"] | None = None
  # 每一則的格式與長度交給 service 驗證，錯誤才會是統一的 VALIDATION 格式
  history: list[dict] | None = None
  # 值交給 service 驗證；型別放寬成任意值，錯的值才會是統一的 VALIDATION 格式
  previousIntent: object | None = None
  openProposal: object | None = None


@router.get("/models")
def listModels(actor: Actor = Depends(askQa)):
  return llm.listModels()


@router.get("/settings")
def settings(actor: Actor = Depends(askQa)):
  # 只回有沒有設定，不回 key；面板用它決定要不要提示「問題會送到 Jev」
  return {"jevConfigured": jev.isConfigured()}


@router.post("/ask")
def ask(body: AskBody, request: Request, actor: Actor = Depends(askQa), conn=connDependency):
  # 每次呼叫時才取 llm.callModel、llm.callModelWithTools 與 jev 的函式：測試可以換掉它們，不用真的連 Ollama
  return service.ask(
    conn, actor, body.question, body.model, request.app.state.qaDatabaseUrl, datetime.now(),
    llm=llm.callModel, mode=body.mode, toolLlm=llm.callModelWithTools,
    chooseTool=jev.chooseTool, jevConfigured=jev.isConfigured, history=body.history,
    previousIntent=body.previousIntent, chooseIntent=intent.chooseIntent, openProposal=body.openProposal,
  )
