from collections.abc import Callable
from contextlib import contextmanager
from itertools import count
from typing import Literal

Stage = Literal["prepare", "route", "intent", "generate_query", "query", "model", "tool", "proposal", "compose"]
EventSink = Callable[[dict], None]


class Progress:
  def __init__(self, emit: EventSink | None = None):
    self.emit = emit
    self.ids = count(1)

  def accepted(self) -> None:
    if self.emit is not None:
      self.emit({"type": "accepted"})

  @contextmanager
  def step(self, stage: Stage, tool: str | None = None):
    stepId = next(self.ids)
    state = "done"

    def fail():
      nonlocal state
      state = "failed"

    self.sendStep(stepId, stage, "running", tool)
    try:
      yield fail
    except Exception:
      fail()
      raise
    finally:
      self.sendStep(stepId, stage, state, tool)

  def sendStep(self, stepId: int, stage: Stage, state: str, tool: str | None) -> None:
    if self.emit is None:
      return
    event = {"type": "step", "id": stepId, "stage": stage, "state": state}
    # 只有工具步驟才帶名稱，其他步驟不放這個欄位，舊的前端與測試照樣能讀
    if tool is not None:
      event["tool"] = tool
    self.emit(event)
