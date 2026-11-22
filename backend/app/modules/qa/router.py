from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.infra.actor import Actor
from app.infra.http import connDependency, requirePermission
from app.modules.qa import llm, service

router = APIRouter()
askQa = requirePermission("qa.ask")


class AskBody(BaseModel):
  question: str
  model: str
  mode: Literal["pipeline", "agent"] | None = None


@router.get("/models")
def listModels(actor: Actor = Depends(askQa)):
  return llm.listModels()


@router.post("/ask")
def ask(body: AskBody, request: Request, actor: Actor = Depends(askQa), conn=connDependency):
  # 每次呼叫時才取 llm.callModel 與 llm.callModelWithTools：測試可以換掉它們，不用真的連 Ollama
  return service.ask(
    conn, actor, body.question, body.model, request.app.state.qaDatabaseUrl, datetime.now(),
    llm=llm.callModel, mode=body.mode, toolLlm=llm.callModelWithTools,
  )
