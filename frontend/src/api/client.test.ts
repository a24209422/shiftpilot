import { mockApi } from "../test/mockApi";
import { ApiError, apiGet, apiSend, onSessionExpired } from "./client";

const errorBody = (code: string, message = "訊息", details: unknown = null) => ({ error: { code, message, details } });

test("testSendAddsCsrfHeaderAndJson", async () => {
  const { calls } = mockApi({ "POST /api/booking/resources": () => ({ status: 201, body: { id: 1 } }) });
  await apiSend("POST", "/api/booking/resources", { name: "A" });
  expect(calls[0].headers.get("X-App-Client")).toBe("web");
  expect(calls[0].headers.get("Content-Type")).toBe("application/json");
  expect(calls[0].body).toEqual({ name: "A" });
});

test("testGetHasNoBodyAndSerializesParams", async () => {
  const { calls } = mockApi({ "GET /api/booking/bookings": () => ({ body: [] }) });
  await apiGet("/api/booking/bookings", { from: "2026-11-16T00:00", to: "2026-11-23T00:00", includeCancelled: undefined });
  expect([...calls[0].params.keys()]).toEqual(["from", "to"]);
  expect(calls[0].body).toBeUndefined();
});

test("testErrorBodyBecomesApiError", async () => {
  const details = { conflicts: [{ bookingId: 1 }] };
  mockApi({ "POST /api/booking/bookings": () => ({ status: 409, body: errorBody("RESOURCE_CONFLICT", "撞期", details) }) });
  const error = await apiSend("POST", "/api/booking/bookings", {}).catch((e) => e);
  expect(error).toBeInstanceOf(ApiError);
  expect(error).toMatchObject({ status: 409, code: "RESOURCE_CONFLICT", message: "撞期", details });
});

test("testNoContentReturnsUndefined", async () => {
  mockApi({ "POST /api/auth/logout": () => ({ status: 204 }) });
  expect(await apiSend("POST", "/api/auth/logout")).toBeUndefined();
});

test("testSessionExpiredFiresOnUnauthenticated", async () => {
  mockApi({ "GET /api/auth/me": () => ({ status: 401, body: errorBody("UNAUTHENTICATED") }) });
  const listener = vi.fn();
  const off = onSessionExpired(listener);
  await apiGet("/api/auth/me").catch(() => {});
  off();
  expect(listener).toHaveBeenCalledTimes(1);
});

test("testLoginFailureDoesNotFireSessionExpired", async () => {
  mockApi({ "POST /api/auth/login": () => ({ status: 401, body: errorBody("INVALID_CREDENTIALS") }) });
  const listener = vi.fn();
  const off = onSessionExpired(listener);
  const error = await apiSend("POST", "/api/auth/login", {}).catch((e) => e);
  off();
  expect(listener).not.toHaveBeenCalled();
  expect(error.code).toBe("INVALID_CREDENTIALS");
});

test("testNonJsonResponseIsNetworkError", async () => {
  globalThis.fetch = (async () => new Response("<html>bad gateway</html>", { status: 502, headers: { "Content-Type": "text/html" } })) as typeof fetch;
  const error = await apiGet("/api/x").catch((e) => e);
  expect(error).toMatchObject({ status: 502, code: "NETWORK" });
});

test("testFetchFailureIsNetworkError", async () => {
  globalThis.fetch = (async () => { throw new TypeError("Failed to fetch"); }) as typeof fetch;
  const error = await apiGet("/api/x").catch((e) => e);
  expect(error).toMatchObject({ code: "NETWORK" });
});
