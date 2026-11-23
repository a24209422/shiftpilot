from collections.abc import Callable
from contextlib import contextmanager
from itertools import count
from typing import Literal

Stage = Literal["prepare", "route", "generate_query", "query", "model", "tool", "proposal", "compose"]
EventSink = Callable[[dict], None]


class Progress:
  def __init__(self, emit: EventSink | None = None):
    self.emit = emit
    self.ids = count(1)

  def accepted(self) -> None:
    if self.emit is not None:
      self.emit({"type": "accepted"})

  @contextmanager
  def step(self, stage: Stage):
    stepId = next(self.ids)
    state = "done"

    def fail():
      nonlocal state
      state = "failed"

    self.sendStep(stepId, stage, "running")
    try:
      yield fail
    except Exception:
      fail()
      raise
    finally:
      self.sendStep(stepId, stage, state)

  def sendStep(self, stepId: int, stage: Stage, state: str) -> None:
    if self.emit is not None:
      self.emit({"type": "step", "id": stepId, "stage": stage, "state": state})
