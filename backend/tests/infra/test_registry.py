from datetime import datetime
from pathlib import Path

import pytest

from app.infra.registry import (
  ModuleManifest,
  clearUnavailabilityProviders,
  collectUnavailability,
  orderModules,
  registerUnavailabilityProvider,
)


def makeManifest(name, dependsOn=()):
  return ModuleManifest(name, name, tuple(dependsOn), (), Path("."))


@pytest.fixture(autouse=True)
def resetProviders():
  clearUnavailabilityProviders()
  yield
  clearUnavailabilityProviders()


def testOrderModulesPutsDependenciesFirst():
  booking = makeManifest("booking", ["core", "org"])
  core = makeManifest("core", ["org"])
  org = makeManifest("org")
  ordered = [manifest.name for manifest in orderModules([booking, core, org])]
  assert ordered.index("org") < ordered.index("core") < ordered.index("booking")


def testOrderModulesRejectsMissingDependency():
  with pytest.raises(ValueError, match="ghost"):
    orderModules([makeManifest("booking", ["ghost"])])


def testOrderModulesRejectsCycle():
  with pytest.raises(ValueError, match="循環"):
    orderModules([makeManifest("a", ["b"]), makeManifest("b", ["a"])])


def testProvidersAreCollectedAndFlattened():
  start, end = datetime(2026, 11, 24, 10), datetime(2026, 11, 24, 11)
  registerUnavailabilityProvider("leave", lambda conn, ids, s, e: [{"employeeId": ids[0], "reason": "請假", "startAt": s, "endAt": e}])
  registerUnavailabilityProvider("shift", lambda conn, ids, s, e: [{"employeeId": ids[0], "reason": "不在班", "startAt": s, "endAt": e}])
  result = collectUnavailability(None, [7], start, end)
  assert sorted(item["reason"] for item in result) == ["不在班", "請假"]
  assert all(item["employeeId"] == 7 for item in result)


def testProviderErrorPropagates():
  def broken(conn, ids, start, end):
    raise RuntimeError("provider failed")

  registerUnavailabilityProvider("broken", broken)
  with pytest.raises(RuntimeError, match="provider failed"):
    collectUnavailability(None, [1], datetime(2026, 11, 24, 10), datetime(2026, 11, 24, 11))
