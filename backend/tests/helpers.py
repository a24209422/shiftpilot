from app.infra.actor import Actor


def insertActor(conn, role="hr", email=None, employeeId=None) -> Actor:
  # 稽核紀錄的 user_id 有外鍵，測試需要真的存在的使用者；密碼雜湊用假值，這裡不登入
  email = email or f"{role}-{employeeId or 'x'}@example.com"
  row = conn.execute(
    "INSERT INTO users (email, password_hash, role, employee_id) VALUES (%s, 'hash', %s, %s) RETURNING id",
    (email, role, employeeId),
  ).fetchone()
  return Actor(userId=row["id"], role=role, employeeId=employeeId)
