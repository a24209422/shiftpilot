import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Booking, BookingSummary } from "../api/types";
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

const summary: BookingSummary = {
  todayBookings: [today1, today2],
  nextBooking: today2,
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

test("testNoNextBooking", async () => {
  open({ ...summary, nextBooking: null, todayBookings: [] });
  expect(await screen.findByText("沒有接下來的排程")).toBeInTheDocument();
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
