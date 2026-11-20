import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Booking, Resource } from "../api/types";
import { bookingRegistration } from "../modules/booking";
import type { MockRoutes } from "../test/mockApi";
import { renderApp, testUser } from "../test/renderApp";
import { createTimelineRegistration } from "./index";

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(2026, 10, 20, 9, 30));
});
afterEach(() => vi.useRealTimers());

const resource = (id: number, name: string, kind: Resource["kind"] = "room"): Resource => ({
  id, name, kind, location: null, capacity: null, features: [], isActive: true, note: null,
});
const bigRoom = resource(1, "3F 大會議室");
const smallRoom = resource(2, "5F 小會議室");
const projector = resource(3, "投影機", "equipment");

const booking = (overrides: Partial<Booking> = {}): Booking => ({
  id: 7, title: "團隊週會", category: "會議", startAt: "2026-11-20T10:00:00", endAt: "2026-11-20T11:00:00", status: "confirmed",
  note: null, createdBy: testUser.id, createdAt: "2026-11-19T08:00:00",
  resources: [{ id: 1, name: "3F 大會議室", kind: "room" }], participants: [], ...overrides,
});

const registrations = [bookingRegistration, createTimelineRegistration([bookingRegistration])];

const open = (options: { permissions?: string[]; route?: string; bookings?: Booking[]; routes?: MockRoutes } = {}) =>
  renderApp({
    route: options.route ?? "/timeline", permissions: options.permissions ?? ["booking.read", "booking.write"], registrations,
    routes: {
      "GET /api/booking/resources": () => ({ body: [projector, smallRoom, bigRoom] }),
      "GET /api/booking/bookings": () => ({ body: options.bookings ?? [] }),
      ...options.routes,
    },
  });

const location = () => screen.getByTestId("location").textContent ?? "";
const searchOf = () => Object.fromEntries(new URLSearchParams(location().split("?")[1] ?? ""));
const rowNames = () => Array.from(document.querySelectorAll(".tlRow:not(.tlAxisRow) .tlName")).map((item) => item.textContent);

test("testRowsGroupedByKindAndSorted", async () => {
  open();
  await screen.findByText("3F 大會議室");
  expect(rowNames()).toEqual(["3F 大會議室", "5F 小會議室", "投影機"]);
  expect(screen.getByText("會議室")).toBeInTheDocument();
  expect(screen.getByText("設備")).toBeInTheDocument();
});

test("testRequestsOneDay", async () => {
  const { api } = open();
  await screen.findByText("3F 大會議室");
  const call = api.calls.find((item) => item.path === "/api/booking/bookings")!;
  expect(call.params.get("from")).toBe("2026-11-20T00:00");
  expect(call.params.get("to")).toBe("2026-11-21T00:00");
});

test("testMultiResourceBookingShowsInEachRow", async () => {
  open({ bookings: [booking({ resources: [{ id: 1, name: "3F 大會議室", kind: "room" }, { id: 2, name: "5F 小會議室", kind: "room" }] })] });
  expect(await screen.findAllByRole("button", { name: "團隊週會" })).toHaveLength(2);
});

test("testClickBarOpensBookingDetail", async () => {
  open({ bookings: [booking()] });
  await userEvent.setup().click(await screen.findByRole("button", { name: "團隊週會" }));
  expect(location()).toBe("/bookings?week=2026-11-20&id=7");
});

test("testClickEmptySlotPrefillsNewBooking", async () => {
  open({ bookings: [booking({ startAt: "2026-11-20T14:30:00", endAt: "2026-11-20T15:30:00" })] });
  await userEvent.setup().click(await screen.findByRole("button", { name: "3F 大會議室 14:00 新增排程" }));
  expect(location().split("?")[0]).toBe("/bookings");
  expect(searchOf()).toMatchObject({ new: "1", week: "2026-11-20", resourceId: "1", startAt: "2026-11-20T14:00", endAt: "2026-11-20T14:30" });
});

test("testEmptySlotStartsAfterPreviousBooking", async () => {
  open({ bookings: [booking({ startAt: "2026-11-20T10:00:00", endAt: "2026-11-20T10:20:00" })] });
  await userEvent.setup().click(await screen.findByRole("button", { name: "3F 大會議室 10:00 新增排程" }));
  expect(searchOf()).toMatchObject({ startAt: "2026-11-20T10:20", endAt: "2026-11-20T11:20" });
});

test("testNoWritePermissionHasNoEmptySlots", async () => {
  open({ permissions: ["booking.read"] });
  await screen.findByText("3F 大會議室");
  expect(screen.queryAllByRole("button", { name: /新增排程/ })).toHaveLength(0);
});

test("testSourceFailureStillShowsRows", async () => {
  open({ routes: { "GET /api/booking/bookings": () => ({ status: 500, body: { error: { code: "INTERNAL", message: "壞了", details: null } } }) } });
  expect(await screen.findByRole("alert")).toHaveTextContent("排程載入失敗");
  expect(screen.getByText("3F 大會議室")).toBeInTheDocument();
});

test("testSubjectsFailureShowsError", async () => {
  open({ routes: { "GET /api/booking/resources": () => ({ status: 500, body: { error: { code: "INTERNAL", message: "壞了", details: null } } }) } });
  expect(await screen.findByText("資源載入失敗")).toBeInTheDocument();
});

test("testEmptyResourcesShowsEmptyText", async () => {
  open({ routes: { "GET /api/booking/resources": () => ({ body: [] }) } });
  expect(await screen.findByText("還沒有資源")).toBeInTheDocument();
});

test("testNextDayFetchesNewDay", async () => {
  const { api } = open();
  await screen.findByText("3F 大會議室");
  await userEvent.setup().click(screen.getByRole("button", { name: "後一天" }));
  await waitFor(() => expect(api.calls.some((call) => call.params.get("from") === "2026-11-21T00:00")).toBe(true));
  expect(location()).toContain("date=2026-11-21");
});

test("testCrossDayBookingIsMarked", async () => {
  open({ bookings: [booking({ startAt: "2026-11-19T22:00:00", endAt: "2026-11-20T09:00:00" })] });
  expect(await screen.findByRole("button", { name: "團隊週會（跨日）" })).toBeInTheDocument();
});

test("testNowLineOnlyOnToday", async () => {
  const today = open();
  await screen.findByText("3F 大會議室");
  expect(screen.getAllByTestId("nowLine").length).toBeGreaterThan(0);
  today.unmount();
  open({ route: "/timeline?date=2026-11-21" });
  await screen.findByText("3F 大會議室");
  expect(screen.queryAllByTestId("nowLine")).toHaveLength(0);
});

test("testHiddenWithoutBookingRead", async () => {
  open({ permissions: [] });
  expect(await screen.findByText("沒有權限看這個頁面")).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "時間軸" })).toBeNull();
});

test("testNavShowsTimelineWithBookingRead", async () => {
  open({ route: "/", routes: { "GET /api/booking/summary": () => ({ body: { todayBookings: [], nextBooking: null, resourceStatus: [], bookingCount: 0, resourceCount: 0 } }) } });
  expect(await screen.findByRole("link", { name: "時間軸" })).toHaveAttribute("href", "/timeline");
});
