from fastapi.testclient import TestClient

from app.main import createApp


def errorOf(response):
  return response.json()["error"]


def testUnexpectedErrorUsesErrorFormatAndHidesDetails(migratedUrl):
  app = createApp(migratedUrl)

  @app.get("/api/test/crash")
  def crash():
    raise RuntimeError("secret internal detail")

  client = TestClient(app, raise_server_exceptions=False, headers={"X-App-Client": "web"})
  response = client.get("/api/test/crash")
  assert response.status_code == 500
  assert response.headers["content-type"].startswith("application/json")
  assert set(errorOf(response)) == {"code", "message", "details"} and errorOf(response)["code"] == "INTERNAL_ERROR"
  assert "secret internal detail" not in response.text


def testOutOfRangeNumbersAreValidationErrorsNotCrashes(client, loginAs):
  loginAs("admin", "admin@example.com")
  window = {"from": "2026-11-24T00:00", "to": "2026-11-24T23:59"}
  cases = [
    client.get("/api/booking/bookings", params={**window, "resourceId": 99999999999}),
    client.get("/api/booking/bookings", params={**window, "employeeId": 99999999999}),
    client.get("/api/core/audit", params={"beforeId": 99999999999}),
    client.post("/api/booking/resources", json={"name": "大", "kind": "room", "capacity": 3000000000}),
  ]
  for response in cases:
    assert response.status_code == 422 and errorOf(response)["code"] == "VALIDATION", response.text
