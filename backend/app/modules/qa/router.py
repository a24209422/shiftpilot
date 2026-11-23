from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.infra.actor import Actor
from app.infra.db import openDb
from app.infra.http import connDependency, requirePermission
from app.modules.qa import jev, llm, service
from app.modules.qa.progress import EventSink
from app.modules.qa.stream import streamQuestion

router = APIRouter()
askQa = requirePermission("qa.ask")


class AskBody(BaseModel):
  question: str
  model: str
  mode: Literal["pipeline", "agent", "jev", "assistant"] | None = None
  # 每一則的格式與長度交給 service 驗證，錯誤才會是統一的 VALIDATION 格式
  history: list[dict] | None = None


@router.get("/models")
def listModels(actor: Actor = Depends(askQa)):
  return llm.listModels()


@router.post("/ask")
def ask(body: AskBody, request: Request, actor: Actor = Depends(askQa), conn=connDependency):
  return askUsingConnection(body, request, actor, conn)


def askUsingConnection(body: AskBody, request: Request, actor: Actor, conn, onEvent: EventSink | None = None):
  # 每次呼叫時才取 llm.callModel、llm.callModelWithTools 與 jev 的函式：測試可以換掉它們，不用真的連 Ollama
  return service.ask(
    conn, actor, body.question, body.model, request.app.state.qaDatabaseUrl, datetime.now(),
    llm=llm.callModel, mode=body.mode, toolLlm=llm.callModelWithTools,
    chooseTool=jev.chooseTool, jevConfigured=jev.isConfigured, history=body.history,
    onEvent=onEvent,
  )


@router.post("/ask/stream")
async def askStream(body: AskBody, request: Request, actor: Actor = Depends(askQa)):
  def ask(onEvent: EventSink):
    with openDb(request.app.state.databaseUrl) as conn:
      return askUsingConnection(body, request, actor, conn, onEvent)

  return await streamQuestion(request, ask)
