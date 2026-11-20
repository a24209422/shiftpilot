from datetime import date, datetime

import pytest

from app.infra.db import openDb
from app.infra.errors import AppError
from app.modules.core.service import listAudit
from app.modules.leave import service
from tests.helpers import insertActor
from tests.leave.world import makeWorld

now = datetime(2026, 11, 21, 10)


@pytest.fixture
def world(migratedUrl):
  return makeWorld(migratedUrl)


def expectError(code, call, *args, **kwargs):
  with pytest.raises(AppError) as info:
    call(*args, **kwargs)
  assert info.value.code == code
  return info.value


def insertRequest(conn, w, employeeId, code, startAt, endAt, hours, status="pending"):
  decided = status in ("approved", "rejected", "cancelled")
  conn.execute(
    "INSERT INTO leave_requests (employee_id, leave_type_id, start_at, end_at, hours, status, decided_by, decided_at, created_by, created_at) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
    (employeeId, w.types[code], startAt, endAt, hours, status,
     w.hrActor.userId if decided else None, now if decided else None, w.hrActor.userId, now),
  )


def balanceOf(balances, typeName):
  return next(item for item in balances if item["leaveTypeName"] == typeName)


def testListLeaveTypesHidesInactiveByDefault(world):
  with openDb(world.url) as conn:
    service.updateLeaveType(conn, world.hrActor, world.types["official"], {"isActive": False})
    assert "公假" not in [item["name"] for item in service.listLeaveTypes(conn)]
    assert "公假" in [item["name"] for item in service.listLeaveTypes(conn, includeInactive=True)]


def testCreateLeaveTypeWritesAudit(world):
  with openDb(world.url) as conn:
    created = service.createLeaveType(conn, world.hrActor, {"code": "family", "name": "家庭照顧假", "paidRatio": 0, "quotaKind": "yearly_cap", "annualCapHours": 56})
    assert created["paidRatio"] == 0 and created["annualCapHours"] == 56 and created["isActive"] is True
    assert listAudit(conn, "leave")[0]["action"] == "createLeaveType"


def testCreateLeaveTypeRejectsBadQuotaKindAndMissingCap(world):
  with openDb(world.url) as conn:
    expectError("VALIDATION", service.createLeaveType, conn, world.hrActor, {"code": "x", "name": "某假", "paidRatio": 1, "quotaKind": "monthly"})
    expectError("VALIDATION", service.createLeaveType, conn, world.hrActor, {"code": "x", "name": "某假", "paidRatio": 1, "quotaKind": "yearly_cap"})
    expectError("DUPLICATE", service.createLeaveType, conn, world.hrActor, {"code": "annual2", "name": "第二種特休", "paidRatio": 1, "quotaKind": "seniority"})


def testUpdateLeaveTypeCannotChangeQuotaKindOrCode(world):
  with openDb(world.url) as conn:
    error = expectError("VALIDATION", service.updateLeaveType, conn, world.hrActor, world.types["personal"], {"quotaKind": "none"})
    assert error.details == {"field": "quotaKind"}
    expectError("VALIDATION", service.updateLeaveType, conn, world.hrActor, world.types["personal"], {"code": "p"})


def testBalancesCountApprovedPendingAndAdjustments(world):
  with openDb(world.url) as conn:
    insertRequest(conn, world, world.alice, "annual", datetime(2026, 3, 2, 9), datetime(2026, 3, 2, 18), 8, "approved")
    insertRequest(conn, world, world.alice, "annual", datetime(2026, 12, 1, 9), datetime(2026, 12, 1, 13), 3)
    insertRequest(conn, world, world.alice, "annual", datetime(2026, 12, 2, 9), datetime(2026, 12, 2, 18), 8, "rejected")
    service.createAdjustment(conn, world.hrActor, {
      "employeeId": world.alice, "leaveTypeId": world.types["annual"], "periodStart": date(2026, 1, 1), "hours": 8, "reason": "公司加給",
    }, now)
    annual = balanceOf(service.getBalances(conn, world.aliceActor, None, date(2026, 11, 21)), "特休")
  assert annual == {
    "leaveTypeId": world.types["annual"], "leaveTypeName": "特休", "quotaKind": "seniority",
    "periodStart": "2026-01-01", "periodEnd": "2026-12-31", "quotaHours": 56, "adjustmentHours": 8,
    "approvedHours": 8, "pendingHours": 3, "remainingHours": 53,
  }


def testBalanceForUnlimitedTypeHasNoRemaining(world):
  with openDb(world.url) as conn:
    insertRequest(conn, world, world.alice, "official", datetime(2026, 5, 4, 9), datetime(2026, 5, 4, 18), 8, "approved")
    official = balanceOf(service.getBalances(conn, world.aliceActor, None, date(2026, 11, 21)), "公假")
  assert official["quotaHours"] is None and official["remainingHours"] is None and official["approvedHours"] == 8


def testBalanceBeforeSixMonthsHasNoAnnualPeriod(world):
  with openDb(world.url) as conn:
    annual = balanceOf(service.getBalances(conn, world.aliceActor, None, date(2025, 3, 1)), "特休")
  assert annual["periodStart"] is None and annual["remainingHours"] == 0


def testBalanceVisibility(world):
  with openDb(world.url) as conn:
    service.getBalances(conn, world.bossActor, world.alice, date(2026, 11, 21))
    service.getBalances(conn, world.hrActor, world.bob, date(2026, 11, 21))
    expectError("FORBIDDEN", service.getBalances, conn, world.bobActor, world.alice, date(2026, 11, 21))
    expectError("FORBIDDEN", service.getBalances, conn, world.aliceActor, world.boss, date(2026, 11, 21))


def testBalanceWithoutEmployeeNeedsEmployeeId(world):
  with openDb(world.url) as conn:
    expectError("NO_EMPLOYEE", service.getBalances, conn, world.adminActor, None, date(2026, 11, 21))


def testAdjustmentMustTargetARealPeriodStart(world):
  with openDb(world.url) as conn:
    base = {"employeeId": world.alice, "leaveTypeId": world.types["annual"], "hours": 8, "reason": "更正"}
    error = expectError("VALIDATION", service.createAdjustment, conn, world.hrActor, {**base, "periodStart": date(2026, 2, 1)}, now)
    assert error.details == {"field": "periodStart"}
    expectError("VALIDATION", service.createAdjustment, conn, world.hrActor, {**base, "leaveTypeId": world.types["official"], "periodStart": date(2026, 1, 1)}, now)
    expectError("VALIDATION", service.createAdjustment, conn, world.hrActor, {**base, "hours": 0, "periodStart": date(2026, 1, 1)}, now)
    expectError("VALIDATION", service.createAdjustment, conn, world.hrActor, {**base, "reason": " ", "periodStart": date(2026, 1, 1)}, now)


def testAdjustmentIsListedAndAudited(world):
  with openDb(world.url) as conn:
    created = service.createAdjustment(conn, world.hrActor, {
      "employeeId": world.alice, "leaveTypeId": world.types["personal"], "periodStart": date(2026, 1, 1), "hours": -8, "reason": "多給了",
    }, now)
    assert created["leaveTypeName"] == "事假" and created["createdByEmail"] == "carol@example.com" and created["periodStart"] == "2026-01-01"
    assert service.listAdjustments(conn, world.alice) == [created]
    assert listAudit(conn, "leave")[0]["action"] == "createLeaveAdjustment"


def testUnusedReportListsPeriodsEndingInRangeWithRemainingHours(world):
  with openDb(world.url) as conn:
    # alice 2025 下半年的 24 小時用了 8 小時；bob 用完；boss 沒用
    insertRequest(conn, world, world.alice, "annual", datetime(2025, 9, 1, 9), datetime(2025, 9, 1, 18), 8, "approved")
    insertRequest(conn, world, world.bob, "annual", datetime(2025, 9, 1, 9), datetime(2025, 9, 3, 18), 24, "approved")
    rows = service.listUnused(conn, date(2025, 12, 1), date(2025, 12, 31))
  byName = {row["employeeName"]: row for row in rows}
  assert set(byName) == {"alice", "boss", "carol"}
  assert byName["alice"] == {
    "employeeId": world.alice, "employeeName": "alice", "departmentName": "工程部",
    "periodStart": "2025-07-01", "periodEnd": "2025-12-31", "quotaHours": 24, "adjustmentHours": 0, "usedHours": 8, "unusedHours": 16,
  }
  with openDb(world.url) as conn:
    assert service.listUnused(conn, date(2026, 1, 1), date(2026, 6, 30)) == []
