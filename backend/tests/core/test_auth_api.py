from app.infra.actor import Actor
from app.infra.db import openDb
from app.modules.core import service

# 這份測試用的標頭名稱；沒帶它的非 GET 請求會被當成可能的跨站請求擋掉
csrfHeader = "X-App-Client"


def errorOf(response):
  return response.json()["error"]


def testLoginSetsHttpOnlySameSiteCookie(client, makeUser):
  userId, password = makeUser("employee", "emp@example.com")
  response = client.post("/api/auth/login", json={"email": "emp@example.com", "password": password})
  assert response.status_code == 200
  cookie = response.headers["set-cookie"]
  assert cookie.startswith("sid=")
  assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie and "Max-Age=43200" in cookie
  assert response.json() == {"user": {"id": userId, "email": "emp@example.com", "role": "employee", "employeeId": None, "employeeName": None}}


def testLoginWithEmployeeReturnsEmployeeName(client, makeUser):
  userId, password = makeUser("employee", "emp@example.com", employee=True)
  user = client.post("/api/auth/login", json={"email": "emp@example.com", "password": password}).json()["user"]
  assert user["employeeId"] is not None and user["employeeName"]


def testLoginWithWrongPasswordIs401WithErrorFormat(client, makeUser):
  makeUser("employee", "emp@example.com")
  response = client.post("/api/auth/login", json={"email": "emp@example.com", "password": "wrong-password"})
  assert response.status_code == 401
  assert set(errorOf(response)) == {"code", "message", "details"}
  assert errorOf(response)["code"] == "INVALID_CREDENTIALS"
  assert "set-cookie" not in response.headers


def testLoginIgnoresEmailCaseAndWhitespace(client, makeUser):
  _, password = makeUser("employee", "emp@example.com")
  assert client.post("/api/auth/login", json={"email": "  EMP@Example.com ", "password": password}).status_code == 200


def testLockedAccountIs429(client, makeUser):
  _, password = makeUser("employee", "emp@example.com")
  for _ in range(5):
    assert client.post("/api/auth/login", json={"email": "emp@example.com", "password": "wrong-password"}).status_code == 401
  locked = client.post("/api/auth/login", json={"email": "emp@example.com", "password": password})
  assert locked.status_code == 429 and errorOf(locked)["code"] == "TOO_MANY_ATTEMPTS"


def testMeRequiresSession(client):
  response = client.get("/api/auth/me")
  assert response.status_code == 401 and errorOf(response)["code"] == "UNAUTHENTICATED"


def testMeReturnsCurrentUser(client, loginAs):
  info = loginAs("hr", "hr@example.com")
  assert client.get("/api/auth/me").json() == {"user": {"id": info["userId"], "email": "hr@example.com", "role": "hr", "employeeId": None, "employeeName": None}}


def testPostWithoutCsrfHeaderIs403(client, makeUser):
  _, password = makeUser("employee", "emp@example.com")
  client.headers.pop(csrfHeader)
  response = client.post("/api/auth/login", json={"email": "emp@example.com", "password": password})
  assert response.status_code == 403 and errorOf(response)["code"] == "CSRF"
  # 不存在的路徑也一樣：檢查在路由之前
  assert errorOf(client.post("/api/nothing"))["code"] == "CSRF"
  assert errorOf(client.delete("/api/nothing"))["code"] == "CSRF"


def testWrongCsrfHeaderValueIs403(client):
  client.headers[csrfHeader] = "other"
  assert errorOf(client.post("/api/auth/login", json={}))["code"] == "CSRF"


def testGetDoesNotNeedCsrfHeader(client, loginAs):
  loginAs("employee")
  client.headers.pop(csrfHeader)
  assert client.get("/api/modules").status_code == 200


def testLogoutInvalidatesSession(client, loginAs):
  loginAs("employee")
  token = client.cookies.get("sid")
  response = client.post("/api/auth/logout")
  assert response.status_code == 204
  assert "Max-Age=0" in response.headers["set-cookie"] or "expires" in response.headers["set-cookie"].lower()
  # 就算有人手上還留著舊的 cookie，伺服器端的 session 也已經刪了
  client.cookies.set("sid", token)
  assert client.get("/api/auth/me").status_code == 401


def testLogoutWithoutSessionIsHarmless(client):
  assert client.post("/api/auth/logout").status_code == 204


def testChangePasswordClearsSessionAndOldPasswordFails(client, loginAs):
  info = loginAs("employee", "emp@example.com")
  token = client.cookies.get("sid")
  wrong = client.post("/api/auth/password", json={"currentPassword": "not-it", "newPassword": "brand-new-pass"})
  assert wrong.status_code == 422 and errorOf(wrong)["code"] == "VALIDATION"
  response = client.post("/api/auth/password", json={"currentPassword": info["password"], "newPassword": "brand-new-pass"})
  assert response.status_code == 204
  client.cookies.set("sid", token)
  assert client.get("/api/auth/me").status_code == 401
  assert client.post("/api/auth/login", json={"email": "emp@example.com", "password": info["password"]}).status_code == 401
  assert client.post("/api/auth/login", json={"email": "emp@example.com", "password": "brand-new-pass"}).status_code == 200


def testModulesListFiltersByPermission(client, newClient, loginAs):
  loginAs("employee", "emp@example.com")
  modules = {item["name"]: item for item in client.get("/api/modules").json()}
  assert set(modules) == {"org", "booking", "shift", "leave", "qa"}
  assert modules["org"]["permissions"] == ["org.read"]
  assert modules["booking"]["permissions"] == ["booking.read", "booking.write"]
  assert modules["booking"]["title"] == "資源預約"
  assert modules["leave"]["permissions"] == ["leave.request"]
  adminClient = newClient()
  loginAs("admin", "admin@example.com", client=adminClient)
  assert {item["name"] for item in adminClient.get("/api/modules").json()} == {"org", "core", "booking", "shift", "leave", "qa"}


def testModulesRequiresSession(client):
  assert client.get("/api/modules").status_code == 401


def testDeactivatedUserCookieIsRejected(client, loginAs, makeUser, migratedUrl):
  info = loginAs("employee", "emp@example.com")
  assert client.get("/api/auth/me").status_code == 200
  adminId, _ = makeUser("admin", "admin@example.com")
  with openDb(migratedUrl) as conn:
    service.updateUser(conn, Actor(userId=adminId, role="admin", employeeId=None), info["userId"], {"isActive": False})
  response = client.get("/api/auth/me")
  assert response.status_code == 401 and errorOf(response)["code"] == "UNAUTHENTICATED"


def testValidationErrorUsesErrorFormat(client):
  response = client.post("/api/auth/login", json={"email": "a@x.com"})
  assert response.status_code == 422
  assert errorOf(response)["code"] == "VALIDATION"
  assert any("password" in str(item["loc"]) for item in errorOf(response)["details"]["fields"])


def testUnknownRouteUsesErrorFormat(client):
  response = client.get("/api/nothing")
  assert response.status_code == 404 and errorOf(response)["code"] == "NOT_FOUND"


def testDeactivatedEmployeeCookieIsRejected(client, loginAs, migratedUrl):
  info = loginAs("employee", "emp@example.com", employee=True)
  assert client.get("/api/auth/me").status_code == 200
  with openDb(migratedUrl) as conn:
    conn.execute("UPDATE employees SET is_active = false WHERE id = %s", (info["employeeId"],))
  assert client.get("/api/auth/me").status_code == 401
  assert client.post("/api/auth/login", json={"email": "emp@example.com", "password": info["password"]}).status_code == 401
