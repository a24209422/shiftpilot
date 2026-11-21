from datetime import datetime

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


@router.get("/models")
def listModels(actor: Actor = Depends(askQa)):
  return llm.listModels()


@router.post("/ask")
def ask(body: AskBody, request: Request, actor: Actor = Depends(askQa), conn=connDependency):
  # 每次呼叫時才取 llm.callModel：測試可以換掉它，不用真的連 Ollama
  return service.ask(conn, actor, body.question, body.model, request.app.state.qaDatabaseUrl, datetime.now(), llm=llm.callModel)
