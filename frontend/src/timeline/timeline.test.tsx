import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Booking, Resource } from "../api/types";
import { bookingRegistration } from "../modules/booking";
import { leaveRegistration } from "../modules/leave";
import { orgRegistration } from "../modules/org";
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

test("testHeaderSplitsMorningAndAfternoon", async () => {
  open();
  await screen.findByText("3F 大會議室");
  expect(screen.getByText("上午")).toBeInTheDocument();
  expect(screen.getByText("下午")).toBeInTheDocument();
  // 預設 08:00–20:00，一小時一欄
  expect(Array.from(document.querySelectorAll(".tlHour")).map((item) => item.textContent)).toEqual(
    ["08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00", "17:00", "18:00", "19:00"],
  );
});

test("testEachRowGetsItsOwnTone", async () => {
  open();
  await screen.findByText("3F 大會議室");
  const tones = Array.from(document.querySelectorAll(".tlRow")).map((row) => Array.from(row.classList).find((name) => name.startsWith("tlTone")));
  expect(tones).toEqual(["tlTone0", "tlTone1", "tlTone2"]);
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

const fullRegistrations = [bookingRegistration, leaveRegistration, orgRegistration, createTimelineRegistration([bookingRegistration, leaveRegistration, orgRegistration])];

const openWithEmployees = (calendar: unknown[]) =>
  renderApp({
    route: "/timeline?date=2026-11-24&view=employees", permissions: ["booking.read", "org.read", "leave.request"], registrations: fullRegistrations,
    routes: {
      "GET /api/booking/resources": () => ({ body: [bigRoom] }),
      "GET /api/booking/bookings": () => ({ body: [] }),
      "GET /api/org/employees": () => ({ body: [{ id: 2, employeeNo: "E2", name: "林小美", email: null, departmentId: 1, jobTitle: "工程師", managerId: null, hiredOn: "2025-01-01", isActive: true, leftOn: null }] }),
      "GET /api/org/departments": () => ({ body: [{ id: 1, name: "工程部", parentId: null }] }),
      "GET /api/leave/calendar": () => ({ body: calendar }),
    },
  });

test("testViewTabsSwitchBetweenResourcesAndEmployees", async () => {
  renderApp({
    route: "/timeline?date=2026-11-24", permissions: ["booking.read", "org.read", "leave.request"], registrations: fullRegistrations,
    routes: {
      "GET /api/booking/resources": () => ({ body: [bigRoom] }),
      "GET /api/booking/bookings": () => ({ body: [] }),
      "GET /api/org/employees": () => ({ body: [] }),
      "GET /api/org/departments": () => ({ body: [] }),
      "GET /api/leave/calendar": () => ({ body: [] }),
    },
  });
  expect(await screen.findByText("3F 大會議室")).toBeInTheDocument();
  await userEvent.setup().click(screen.getByRole("tab", { name: "員工" }));
  await waitFor(() => expect(location()).toContain("view=employees"));
  expect(location()).toContain("date=2026-11-24");
});

test("testLeaveBlockWithoutLinkIsNotClickable", async () => {
  openWithEmployees([{ id: 6, employeeId: 2, startAt: "2026-11-24T09:00:00", endAt: "2026-11-24T18:00:00", status: "approved", leaveTypeName: null, segments: [{ startAt: "2026-11-24T09:00:00", endAt: "2026-11-24T18:00:00" }] }]);
  // 導覽列也有「請假」兩個字，所以用區塊的 title 找
  const block = await screen.findByTitle(/^請假 /);
  expect(block.tagName).toBe("DIV");
  expect(block).toHaveClass("tlBlock");
});

test("testLeaveBlockWithLinkOpensRequest", async () => {
  openWithEmployees([{ id: 5, employeeId: 2, startAt: "2026-11-24T09:00:00", endAt: "2026-11-24T18:00:00", status: "pending", leaveTypeName: "事假", segments: [{ startAt: "2026-11-24T09:00:00", endAt: "2026-11-24T18:00:00" }] }]);
  await userEvent.setup().click(await screen.findByRole("button", { name: /事假（待核准）/ }));
  expect(location()).toBe("/leave?id=5");
});
