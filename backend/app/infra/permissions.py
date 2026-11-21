# 角色對應哪些權限寫在程式裡，不放資料庫、不能在畫面上改（設計文件「權限的預設」那張表）
_baseline = frozenset({"org.read", "booking.read", "booking.write", "leave.request", "shift.read", "qa.ask"})
_hr = _baseline | {"org.manage", "booking.writeAny", "leave.manage", "shift.manage"}
_admin = _hr | {"booking.resources.manage", "core.users.manage", "core.audit.read"}

rolePermissions: dict[str, frozenset[str]] = {
  "employee": _baseline,
  "manager": _baseline,
  "hr": frozenset(_hr),
  "admin": frozenset(_admin),
}


def permissionsFor(role: str) -> frozenset[str]:
  return rolePermissions.get(role, frozenset())


def hasPermission(role: str, permission: str) -> bool:
  return permission in permissionsFor(role)
