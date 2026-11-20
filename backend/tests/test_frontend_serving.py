import pytest
from fastapi.testclient import TestClient

from app.main import createApp


@pytest.fixture
def dist(tmp_path):
  folder = tmp_path / "dist"
  (folder / "assets").mkdir(parents=True)
  (folder / "index.html").write_text('<div id="root"></div>', encoding="utf-8")
  (folder / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
  (folder / "favicon.svg").write_text("<svg></svg>", encoding="utf-8")
  (tmp_path / "secret.txt").write_text("TOP-SECRET", encoding="utf-8")
  return folder


@pytest.fixture
def servedClient(migratedUrl, dist):
  return TestClient(createApp(migratedUrl, frontendDir=dist))


def testRootServesIndexHtml(servedClient):
  response = servedClient.get("/")
  assert response.status_code == 200
  assert response.headers["content-type"].startswith("text/html")
  assert 'id="root"' in response.text


def testClientRoutesFallBackToIndexHtml(servedClient):
  for path in ("/bookings", "/users/3"):
    response = servedClient.get(path)
    assert response.status_code == 200 and 'id="root"' in response.text


def testAssetsAreServed(servedClient):
  assert servedClient.get("/assets/app.js").text == "console.log(1)"
  assert servedClient.get("/favicon.svg").status_code == 200


def testUnknownApiPathStaysJson404(servedClient):
  response = servedClient.get("/api/nope")
  assert response.status_code == 404
  assert response.headers["content-type"].startswith("application/json")
  assert response.json()["error"]["code"] == "NOT_FOUND"


def testApiStillWorks(servedClient):
  response = servedClient.get("/api/auth/me")
  assert response.status_code == 401 and response.json()["error"]["code"] == "UNAUTHENTICATED"


def testPathTraversalDoesNotEscapeDist(servedClient):
  for path in ("/..%2fsecret.txt", "/assets/..%2f..%2fsecret.txt", "/%2e%2e/secret.txt"):
    assert "TOP-SECRET" not in servedClient.get(path).text


def testWithoutBuildOnlyApi(migratedUrl, tmp_path):
  client = TestClient(createApp(migratedUrl, frontendDir=tmp_path / "missing"))
  response = client.get("/")
  assert response.status_code == 404 and response.headers["content-type"].startswith("application/json")
