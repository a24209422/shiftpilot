import asyncio
import json
import logging
import threading
from collections.abc import Callable
from contextlib import suppress

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response, StreamingResponse

from app.infra.errors import AppError
from app.modules.qa.progress import EventSink

logger = logging.getLogger(__name__)


class ClientLeft(Exception):
  """Stop the worker at the next progress boundary."""


def encodeEvent(event: dict) -> bytes:
  return (json.dumps(jsonable_encoder(event), ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


class QuestionStream:
  def __init__(self):
    self.loop = asyncio.get_running_loop()
    self.outgoing: asyncio.Queue[bytes | AppError | None] = asyncio.Queue()
    self.closed = threading.Event()
    self.accepted = False

  def publish(self, item: bytes | AppError | None) -> None:
    if self.closed.is_set():
      raise ClientLeft()
    try:
      self.loop.call_soon_threadsafe(self.outgoing.put_nowait, item)
    except RuntimeError as error:
      if not self.loop.is_closed():
        raise
      raise ClientLeft() from error

  def emit(self, event: dict) -> None:
    self.publish(encodeEvent(event))
    if event["type"] == "accepted":
      self.accepted = True

  def errorEvent(self, error: AppError) -> bytes | AppError:
    if not self.accepted:
      return error
    return encodeEvent({"type": "error", "status": error.status, "error": {
      "code": error.code, "message": error.message, "details": error.details,
    }})

  def terminalEvent(self, ask: Callable[[EventSink], dict]) -> bytes | AppError:
    try:
      return encodeEvent({"type": "result", "answer": ask(self.emit)})
    except AppError as error:
      return self.errorEvent(error)

  def run(self, ask: Callable[[EventSink], dict]) -> None:
    with suppress(ClientLeft):
      try:
        try:
          terminal = self.terminalEvent(ask)
        except ClientLeft:
          return
        except Exception:
          logger.exception("問答串流發生未預期的錯誤")
          terminal = self.errorEvent(AppError("INTERNAL_ERROR", "系統發生未預期的錯誤", 500))
        self.publish(terminal)
      finally:
        self.publish(None)

  async def watchDisconnect(self, request: Request) -> None:
    while (await request.receive())["type"] != "http.disconnect":
      pass
    self.closed.set()
    self.outgoing.put_nowait(None)

  async def chunks(self, first: bytes):
    yield first
    while not self.closed.is_set():
      item = await self.outgoing.get()
      if item is None or self.closed.is_set():
        return
      # After accepted, the worker encodes all remaining events as NDJSON.
      assert isinstance(item, bytes)
      yield item


class QuestionStreamResponse(StreamingResponse):
  def __init__(self, stream: QuestionStream, first: bytes, watcher: asyncio.Task):
    super().__init__(stream.chunks(first), media_type="application/x-ndjson", headers={"Cache-Control": "no-store"})
    self.stream = stream
    self.watcher = watcher

  async def __call__(self, scope, receive, send):
    # The watcher already owns receive, including before the response starts.
    try:
      await self.stream_response(send)
    except OSError:
      pass
    finally:
      self.stream.closed.set()
      self.watcher.cancel()
      with suppress(asyncio.CancelledError):
        await self.watcher


async def streamQuestion(request: Request, ask: Callable[[EventSink], dict]) -> Response:
  stream = QuestionStream()
  watcher = asyncio.create_task(stream.watchDisconnect(request))
  # The worker owns the question slot and its database connections until it exits.
  stream.loop.run_in_executor(None, stream.run, ask)
  response = None
  try:
    first = await stream.outgoing.get()
    if isinstance(first, AppError):
      raise first
    if first is None:
      return Response(status_code=204)
    response = QuestionStreamResponse(stream, first, watcher)
    return response
  finally:
    if response is None:
      stream.closed.set()
      watcher.cancel()
      with suppress(asyncio.CancelledError):
        await watcher
