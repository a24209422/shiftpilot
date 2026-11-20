import pytest


def errorOf(response):
  return response.json()["error"]


@pytest.fixture
def admin(newClient, loginAs):
  adminClient = newClient()
  info = loginAs("admin", "admin@example.com", client=adminClient)
  return adminClient, info


def testNonAdminCannotManageUsers(client, newClient, loginAs):
  loginAs("hr", "hr@example.com")
  for response in (
    client.get("/api/core/users"),
    client.post("/api/core/users", json={"email": "x@x.com", "password": "correct-horse", "role": "employee"}),
    client.patch("/api/core/users/1", json={"role": "admin"}),
    client.post("/api/core/users/1/password", json={"newPassword": "correct-horse"}),
    client.get("/api/core/audit"),
  ):
    assert response.status_code == 403 and errorOf(response)["code"] == "FORBIDDEN"
  other = newClient()
  assert other.get("/api/core/users").status_code == 401


def testAdminCreatesUserAndTheyCanLogin(admin, newClient):
  adminClient, _ = admin
  created = adminClient.post("/api/core/users", json={"email": " New@Example.com ", "password": "correct-horse", "role": "manager"})
  assert created.status_code == 201
  user = created.json()
  assert user["email"] == "New@Example.com" and user["role"] == "manager" and user["isActive"] is True and user["employeeId"] is None
  fresh = newClient()
  login = fresh.post("/api/auth/login", json={"email": "new@example.com", "password": "correct-horse"})
  assert login.status_code == 200 and login.json()["user"]["id"] == user["id"]


def testCreateUserValidatesInput(admin):
  adminClient, _ = admin
  assert adminClient.post("/api/core/users", json={"email": "a@x.com", "password": "short", "role": "employee"}).status_code == 422
  assert adminClient.post("/api/core/users", json={"email": "a@x.com", "password": "correct-horse", "role": "boss"}).status_code == 422
  assert adminClient.post("/api/core/users", json={"email": "a@x.com"}).status_code == 422
  duplicate = adminClient.post("/api/core/users", json={"email": "ADMIN@example.com", "password": "correct-horse", "role": "employee"})
  assert duplicate.status_code == 409 and errorOf(duplicate)["code"] == "DUPLICATE"


def testAdminDeactivatesUserAndSessionsDie(admin, client, loginAs):
  adminClient, _ = admin
  info = loginAs("employee", "emp@example.com")
  assert client.get("/api/auth/me").status_code == 200
  response = adminClient.patch(f"/api/core/users/{info['userId']}", json={"isActive": False})
  assert response.status_code == 200 and response.json()["isActive"] is False
  assert client.get("/api/auth/me").status_code == 401
  assert client.post("/api/auth/login", json={"email": "emp@example.com", "password": info["password"]}).status_code == 401
  assert adminClient.patch(f"/api/core/users/{info['userId']}", json={"isActive": True, "role": "hr"}).json()["role"] == "hr"


def testAdminCannotDeactivateSelf(admin):
  adminClient, info = admin
  response = adminClient.patch(f"/api/core/users/{info['userId']}", json={"isActive": False})
  assert response.status_code == 422 and errorOf(response)["code"] == "CANNOT_MODIFY_SELF"
  assert adminClient.patch(f"/api/core/users/{info['userId']}", json={"role": "employee"}).status_code == 422
  assert adminClient.get("/api/auth/me").status_code == 200


def testPatchUnknownUserIs404(admin):
  adminClient, _ = admin
  assert adminClient.patch("/api/core/users/9999", json={"role": "hr"}).status_code == 404
  assert adminClient.post("/api/core/users/9999/password", json={"newPassword": "correct-horse"}).status_code == 404


def testAdminResetsPassword(admin, client, loginAs):
  adminClient, _ = admin
  info = loginAs("employee", "emp@example.com")
  assert adminClient.post(f"/api/core/users/{info['userId']}/password", json={"newPassword": "short"}).status_code == 422
  response = adminClient.post(f"/api/core/users/{info['userId']}/password", json={"newPassword": "brand-new-pass"})
  assert response.status_code == 204
  assert client.get("/api/auth/me").status_code == 401
  assert client.post("/api/auth/login", json={"email": "emp@example.com", "password": info["password"]}).status_code == 401
  assert client.post("/api/auth/login", json={"email": "emp@example.com", "password": "brand-new-pass"}).status_code == 200


def testUserListNeverIncludesPasswordHash(admin, loginAs):
  adminClient, _ = admin
  loginAs("employee", "emp@example.com", employee=True)
  users = adminClient.get("/api/core/users").json()
  assert len(users) == 2
  for user in users:
    assert not any("hash" in key.lower() or "password" in key.lower() for key in user)
  linked = next(user for user in users if user["email"] == "emp@example.com")
  assert linked["employeeId"] is not None and linked["employeeName"]
  created = adminClient.post("/api/core/users", json={"email": "n@x.com", "password": "correct-horse", "role": "employee"}).json()
  assert "$argon2" not in str(created) and "correct-horse" not in str(created)


def testAuditEndpointFiltersByModuleAndOnlyAdmin(admin, newClient, loginAs):
  adminClient, _ = admin
  hrClient = newClient()
  loginAs("hr", "hr@example.com", client=hrClient)
  hrClient.post("/api/org/departments", json={"name": "工程部"})
  adminClient.post("/api/core/users", json={"email": "n@x.com", "password": "correct-horse", "role": "employee"})
  everything = adminClient.get("/api/core/audit").json()
  assert [row["id"] for row in everything] == sorted((row["id"] for row in everything), reverse=True)
  assert {"createDepartment", "createUser"} <= {row["action"] for row in everything}
  orgOnly = adminClient.get("/api/core/audit", params={"module": "org"}).json()
  assert [row["action"] for row in orgOnly] == ["createDepartment"] and orgOnly[0]["after"]["name"] == "工程部"
  firstPage = adminClient.get("/api/core/audit", params={"limit": 1}).json()
  assert len(firstPage) == 1
  nextPage = adminClient.get("/api/core/audit", params={"limit": 1, "beforeId": firstPage[0]["id"]}).json()
  assert nextPage and nextPage[0]["id"] < firstPage[0]["id"]
  assert hrClient.get("/api/core/audit").status_code == 403
  assert adminClient.get("/api/core/audit", params={"limit": 0}).status_code == 422
  assert adminClient.get("/api/core/audit", params={"limit": 100000}).status_code == 422
