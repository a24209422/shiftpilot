from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from psycopg import Connection


@dataclass(frozen=True)
class ModuleManifest:
  name: str
  title: str
  dependsOn: tuple[str, ...]
  permissions: tuple[str, ...]
  migrationsDir: Path


def orderModules(manifests: list[ModuleManifest]) -> list[ModuleManifest]:
  byName = {manifest.name: manifest for manifest in manifests}
  ordered: list[ModuleManifest] = []
  done: set[str] = set()
  visiting: list[str] = []

  def visit(name: str) -> None:
    if name in done:
      return
    if name in visiting:
      raise ValueError(f"模組依賴有循環：{' -> '.join(visiting + [name])}")
    visiting.append(name)
    for dependency in byName[name].dependsOn:
      if dependency not in byName:
        raise ValueError(f"模組 {name} 依賴不存在的模組 {dependency}")
      visit(dependency)
    visiting.pop()
    done.add(name)
    ordered.append(byName[name])

  for manifest in manifests:
    visit(manifest.name)
  return ordered


UnavailabilityProvider = Callable[[Connection, list[int], datetime, datetime], list[dict]]

# 之後的請假、排班模組在這裡登記，資源預約檢查參加者時就會自動帶出警告，不用改資源預約的程式
unavailabilityProviders: dict[str, UnavailabilityProvider] = {}


def registerUnavailabilityProvider(name: str, provider: UnavailabilityProvider) -> None:
  unavailabilityProviders[name] = provider


def clearUnavailabilityProviders() -> None:
  unavailabilityProviders.clear()


def collectUnavailability(conn: Connection, employeeIds: list[int], startAt: datetime, endAt: datetime) -> list[dict]:
  # 提供者出錯不吞掉：吞掉會讓「請假中的人」靜悄悄地不出現警告
  result: list[dict] = []
  for provider in unavailabilityProviders.values():
    result.extend(provider(conn, employeeIds, startAt, endAt))
  return result
