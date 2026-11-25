import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Booking, BookingSummary } from "../api/types";
import { allRegistrations } from "../modules";
import { bookingRegistration } from "../modules/booking";
import type { MockRoutes } from "../test/mockApi";
import { renderApp } from "../test/renderApp";

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(2026, 10, 20, 9, 30));
});
afterEach(() => vi.useRealTimers());

const booking = (id: number, title: string, startAt: string, endAt: string): Booking => ({
  id, title, category: "會議", startAt, endAt, status: "confirmed", note: null, createdBy: 1, createdAt: "2026-11-16T08:00:00",
  resources: [{ id: 1, name: "3F 大會議室", kind: "room" }], participants: [{ employeeId: 2, name: "林小美", role: "organizer" }],
});
const today1 = booking(1, "晨會", "2026-11-20T09:00:00", "2026-11-20T10:00:00");
const today2 = booking(2, "客戶簡報", "2026-11-20T14:00:00", "2026-11-20T15:00:00");
const mine: Booking = {
  ...booking(7, "一對一", "2026-11-20T11:00:00", "2026-11-20T11:30:00"),
  participants: [{ employeeId: 2, name: "林小美", role: "organizer" }, { employeeId: 3, name: "黃志強", role: "attendee" }],
};

const summary: BookingSummary = {
  todayBookings: [today1, today2],
  nextBooking: today2,
  myNextBooking: mine,
  resourceStatus: [
    { resourceId: 1, name: "3F 大會議室", kind: "room", currentBooking: today1 },
    { resourceId: 2, name: "2F 小會議室", kind: "room", currentBooking: null },
    { resourceId: 4, name: "公務車（白色）", kind: "vehicle", currentBooking: null },
  ],
  bookingCount: 5,
  resourceCount: 4,
};

const open = (data: BookingSummary = summary, routes: MockRoutes = {}) =>
  renderApp({
    route: "/", permissions: ["booking.read", "booking.write"], registrations: [bookingRegistration],
    routes: {
      "GET /api/booking/summary": () => ({ body: data }),
      "GET /api/booking/bookings": () => ({ body: [] }),
      "GET /api/booking/resources": () => ({ body: [] }),
      "GET /api/org/employees": () => ({ body: [] }),
      ...routes,
    },
  });

const statValue = async (label: string) => within((await screen.findByText(label, { selector: ".statLabel" })).closest(".stat") as HTMLElement).getByText(/./, { selector: ".statValue" });

test("testStatsFromSummary", async () => {
  open();
  expect((await statValue("今天的排程")).textContent).toBe("2");
  expect((await statValue("會議室使用中")).textContent).toBe("1/2");
  expect((await statValue("接下來的排程")).textContent).toBe("5");
  expect((await statValue("資源")).textContent).toBe("4");
  expect(screen.getByText("下一場 14:00")).toBeInTheDocument();
});

test("testRoomsRightNowListsOnlyRooms", async () => {
  open();
  const panel = (await screen.findByText("Rooms right now")).closest(".panel") as HTMLElement;
  expect(within(panel).getByText("3F 大會議室")).toBeInTheDocument();
  expect(within(panel).getByText("使用中")).toBeInTheDocument();
  expect(within(panel).getByText("空著")).toBeInTheDocument();
  expect(within(panel).queryByText("公務車（白色）")).toBeNull();
});

const nextUpCard = async () => (await screen.findByText("Next up")).closest(".feature") as HTMLElement;

test("testNextUpShowsMyNextBookingNotCompanyWide", async () => {
  open();
  const card = await nextUpCard();
  expect(within(card).getByText("一對一")).toBeInTheDocument();
  expect(within(card).getByText("1 小時 30 分鐘後開始")).toBeInTheDocument();
  expect(within(card).getByText("參加者：林小美、黃志強")).toBeInTheDocument();
  expect(within(card).queryByText("客戶簡報")).toBeNull();
  // 現在時間的戳記會被誤認成會議時間，已拿掉
  expect(card.querySelector(".stamp")).toBeNull();
});

test("testNextUpCountdownForLaterDays", async () => {
  open({ ...summary, myNextBooking: booking(8, "週會", "2026-11-21T10:00:00", "2026-11-21T11:00:00") });
  expect(within(await nextUpCard()).getByText("明天開始")).toBeInTheDocument();
});

test("testNextUpListsAtMostThreeParticipants", async () => {
  const names = ["林小美", "黃志強", "陳大文", "張雅婷", "王小明"];
  const crowded = { ...mine, participants: names.map((name, index) => ({ employeeId: index + 2, name, role: "attendee" as const })) };
  open({ ...summary, myNextBooking: crowded });
  expect(within(await nextUpCard()).getByText("參加者：林小美、黃志強、陳大文等 5 人")).toBeInTheDocument();
});

test("testNoNextBooking", async () => {
  open({ ...summary, nextBooking: null, myNextBooking: null, todayBookings: [] });
  expect(within(await nextUpCard()).getByText("你接下來沒有排程")).toBeInTheDocument();
});

test("testNewBookingButtonOpensForm", async () => {
  open();
  await userEvent.setup().click(await screen.findByRole("button", { name: "新增排程" }));
  expect(await screen.findByLabelText("標題")).toBeInTheDocument();
  expect(screen.getByTestId("location").textContent).toContain("/bookings?new=1");
});

test("testNoLeaveOrDemoContent", async () => {
  open();
  await screen.findByText("Next up");
  expect(document.body.textContent).not.toMatch(/請假|DEMO|Needs a decision/);
});

const monthRoutes: MockRoutes = {
  "GET /api/org/calendarDays": () => ({ body: [{ day: "2026-11-27", kind: "holiday", name: "測試假日" }] }),
  "GET /api/booking/bookings": () => ({ body: [today1, today2, booking(3, "跨日", "2026-11-21T22:00:00", "2026-11-22T06:00:00")] }),
};

const openWithOrg = () =>
  renderApp({
    route: "/", permissions: ["booking.read", "booking.write", "org.read"], registrations: allRegistrations,
    routes: {
      "GET /api/booking/summary": () => ({ body: summary }),
      "GET /api/booking/resources": () => ({ body: [] }),
      "GET /api/org/employees": () => ({ body: [] }),
      ...monthRoutes,
    },
  });

test("testCalendarIsNotATile", async () => {
  openWithOrg();
  const launcher = (await screen.findByText("All modules")).closest(".modulesBlock") as HTMLElement;
  expect(within(launcher).queryByText("行事曆")).toBeNull();
  expect(within(launcher).getByText("排程")).toBeInTheDocument();
});

test("testMonthCalendarShowsHolidaysAndBookingCounts", async () => {
  const { api } = openWithOrg();
  const calendar = (await screen.findByText("2026 / 11")).closest(".monthBlock") as HTMLElement;
  expect(await within(calendar).findByText("測試假日")).toBeInTheDocument();
  const cell = (day: string) => calendar.querySelector(`[data-day="${day}"]`) as HTMLElement;
  await waitFor(() => expect(within(cell("2026-11-20")).getByText("2 筆")).toBeInTheDocument());
  // 跨日的排程兩天都要算到
  expect(within(cell("2026-11-21")).getByText("1 筆")).toBeInTheDocument();
  expect(within(cell("2026-11-22")).getByText("1 筆")).toBeInTheDocument();
  const days = api.calls.find((call) => call.path === "/api/org/calendarDays")!;
  expect([days.params.get("from"), days.params.get("to")]).toEqual(["2026-11-01", "2026-11-30"]);
});

test("testClickingDayOpensThatWeek", async () => {
  openWithOrg();
  const calendar = (await screen.findByText("2026 / 11")).closest(".monthBlock") as HTMLElement;
  await userEvent.setup().click(calendar.querySelector('[data-day="2026-11-27"]') as HTMLElement);
  await waitFor(() => expect(screen.getByTestId("location").textContent).toBe("/bookings?week=2026-11-23"));
});

test("testMonthNavigation", async () => {
  const { api } = openWithOrg();
  await screen.findByText("2026 / 11");
  await userEvent.setup().click(screen.getByRole("button", { name: "下個月" }));
  expect(await screen.findByText("2026 / 12")).toBeInTheDocument();
  await waitFor(() => expect(api.calls.some((call) => call.path === "/api/org/calendarDays" && call.params.get("from") === "2026-12-01")).toBe(true));
});

test("testCalendarNotInSidebarButManageButtonForHr", async () => {
  renderApp({
    route: "/", permissions: ["booking.read", "org.read", "org.manage"], registrations: allRegistrations,
    routes: { "GET /api/booking/summary": () => ({ body: summary }), ...monthRoutes },
  });
  await screen.findByText("2026 / 11");
  expect(screen.queryByRole("link", { name: /行事曆/ })).toBeNull();
  await userEvent.setup().click(screen.getByRole("button", { name: "管理假日" }));
  await waitFor(() => expect(screen.getByTestId("location").textContent).toBe("/calendar"));
});

test("testManageHolidaysHiddenWithoutPermission", async () => {
  openWithOrg();
  await screen.findByText("2026 / 11");
  expect(screen.queryByRole("button", { name: "管理假日" })).toBeNull();
});

test("testDayPopoverListsThatDaysBookings", async () => {
  openWithOrg();
  const calendar = (await screen.findByText("2026 / 11")).closest(".monthBlock") as HTMLElement;
  const cell = () => calendar.querySelector('[data-day="2026-11-20"]') as HTMLElement;
  await waitFor(() => expect(cell().querySelector(".dayPopover")).not.toBeNull());
  const popover = cell().querySelector(".dayPopover") as HTMLElement;
  expect(within(popover).getByText("晨會")).toBeInTheDocument();
  expect(within(popover).getByText("09:00–10:00")).toBeInTheDocument();
  expect(within(popover).getByText("客戶簡報")).toBeInTheDocument();
  // 跨日的排程顯示完整日期時間
  const crossPopover = calendar.querySelector('[data-day="2026-11-22"] .dayPopover') as HTMLElement;
  expect(within(crossPopover).getByText("11/21（六） 22:00 – 11/22（日） 06:00")).toBeInTheDocument();
  // 沒有排程的日子沒有小框
  expect(calendar.querySelector('[data-day="2026-11-25"] .dayPopover')).toBeNull();
});

test("testBusyDaysMarkedAndHomeHasNoSubtitle", async () => {
  openWithOrg();
  const calendar = (await screen.findByText("2026 / 11")).closest(".monthBlock") as HTMLElement;
  await waitFor(() => expect(calendar.querySelector('[data-day="2026-11-20"]')).toHaveClass("busy"));
  expect(calendar.querySelector('[data-day="2026-11-25"]')).not.toHaveClass("busy");
  expect(document.querySelector(".pageHead .sub")).toBeNull();
  expect(screen.getByText("All modules").textContent).toBe("All modules");
});

const openWithLeave = (toApprove: unknown[]) =>
  renderApp({
    route: "/", permissions: ["booking.read", "leave.request"], registrations: [bookingRegistration],
    routes: {
      "GET /api/booking/summary": () => ({ body: summary }),
      "GET /api/booking/bookings": () => ({ body: [] }),
      "GET /api/booking/resources": () => ({ body: [] }),
      "GET /api/org/employees": () => ({ body: [] }),
      "GET /api/leave/requests": ({ params }) => ({ body: params.get("scope") === "toApprove" ? toApprove : [] }),
    },
  });

test("testPendingLeaveStatLinksToApproveTab", async () => {
  openWithLeave([{ id: 6, startAt: "2026-11-25T09:00:00" }, { id: 5, startAt: "2026-11-24T09:00:00" }]);
  const stat = await screen.findByRole("button", { name: /待審核請假/ });
  expect(within(stat).getByText("2", { selector: ".statValue" })).toBeInTheDocument();
  expect(within(stat).getByText("最早 11/24（二）", { selector: ".statNote" })).toBeInTheDocument();
  await userEvent.setup().click(stat);
  expect(screen.getByTestId("location").textContent).toBe("/leave?tab=approve");
});

test("testNoPendingLeaveStatWhenNothingToApprove", async () => {
  openWithLeave([]);
  await screen.findByText("今天的排程", { selector: ".statLabel" });
  expect(screen.queryByText("待審核請假")).not.toBeInTheDocument();
});
