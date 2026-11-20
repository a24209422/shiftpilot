import pytest

from app.infra.permissions import hasPermission, permissionsFor

permissionNames = [
  "org.read", "org.manage", "booking.read", "booking.write", "booking.writeAny",
  "booking.resources.manage", "core.users.manage", "core.audit.read",
]

# 設計文件「權限的預設」那張表，一格一格寫出來；用 1 代表 ✓、0 代表 —
expectedTable = {
  "employee": dict(zip(permissionNames, [1, 0, 1, 1, 0, 0, 0, 0])),
  "manager": dict(zip(permissionNames, [1, 0, 1, 1, 0, 0, 0, 0])),
  "hr": dict(zip(permissionNames, [1, 1, 1, 1, 1, 0, 0, 0])),
  "admin": dict(zip(permissionNames, [1, 1, 1, 1, 1, 1, 1, 1])),
}


@pytest.mark.parametrize("role", list(expectedTable))
@pytest.mark.parametrize("permission", permissionNames)
def testPermissionTableCell(role, permission):
  assert hasPermission(role, permission) is bool(expectedTable[role][permission])


@pytest.mark.parametrize("role", list(expectedTable))
def testPermissionsForMatchesTable(role):
  assert permissionsFor(role) == frozenset(name for name, allowed in expectedTable[role].items() if allowed)


def testUnknownRoleAndUnknownPermissionAreDenied():
  assert hasPermission("intern", "org.read") is False
  assert hasPermission("admin", "payroll.read") is False
  assert permissionsFor("intern") == frozenset()
