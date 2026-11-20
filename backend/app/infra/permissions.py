# 最小版：任務 10 的修改、取消只需要知道誰有 booking.writeAny；完整的角色表在任務 11 補上
rolePermissions: dict[str, frozenset[str]] = {
  "employee": frozenset(),
  "manager": frozenset(),
  "hr": frozenset({"booking.writeAny"}),
  "admin": frozenset({"booking.writeAny"}),
}


def hasPermission(role: str, permission: str) -> bool:
  return permission in rolePermissions.get(role, frozenset())
