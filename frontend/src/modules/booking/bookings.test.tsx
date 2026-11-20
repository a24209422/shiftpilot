import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Booking, Employee, Resource } from "../../api/types";
import type { MockRoutes } from "../../test/mockApi";
import { renderApp, testUser } from "../../test/renderApp";
import { bookingRegistration } from "./index";

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(2026, 10, 20, 9, 30));
});
afterEach(() => vi.useRealTimers());

const room: Resource = { id: 1, name: "3F 大會議室", kind: "room", location: null, capacity: 12, features: [], isActive: true, note: null };
const employee = (id: number, name: string): Employee => ({
  id, employeeNo: `E00${id}`, name, email: null, departmentId: 1, jobTitle: "工程師", managerId: null, hiredOn: "2024-01-01", isActive: true, leftOn: null,
});
const booking: Booking = {
  id: 7, title: "團隊週會", category: "會議", startAt: "2026-11-17T10:00:00", endAt: "2026-11-17T11:00:00", status: "confirmed", note: null,
  createdBy: testUser.id, createdAt: "2026-11-16T08:00:00",
  resources: [{ id: 1, name: "3F 大會議室", kind: "room" }],
  participants: [{ employeeId: 2, name: "林小美", role: "organizer" }, { employeeId: 3, name: "黃志強", role: "attendee" }],
};
const base = ["booking.read", "booking.write"];
const owner = { ...testUser, employeeId: 2, employeeName: "林小美" };

const open = (options: { permissions?: string[]; user?: typeof testUser | null; route?: string; routes?: MockRoutes } = {}) =>
  renderApp({
    route: options.route ?? "/bookings", permissions: options.permissions ?? base, user: options.user === undefined ? owner : options.user,
    registrations: [bookingRegistration],
    routes: {
      "GET /api/booking/bookings": () => ({ body: [booking] }),
      "GET /api/booking/resources": () => ({ body: [room] }),
      "GET /api/org/employees": () => ({ body: [employee(2, "林小美"), employee(3, "黃志強")] }),
      ...options.routes,
    },
  });

const conflictError = (code: string, message: string, conflicts: unknown[]) => ({ status: 409, body: { error: { code, message, details: { conflicts } } } });

async function fillBasics(user: ReturnType<typeof userEvent.setup>) {
  await user.type(await screen.findByLabelText("標題"), "新會議");
  await user.type(screen.getByLabelText("類別"), "會議");
}

test("testWeekRangeRequestedAndNavigable", async () => {
  const { api } = open();
  await screen.findByText("團隊週會");
  const first = api.calls.find((call) => call.path === "/api/booking/bookings")!;
  expect(first.params.get("from")).toBe("2026-11-16T00:00");
  expect(first.params.get("to")).toBe("2026-11-23T00:00");
  await userEvent.setup().click(screen.getByRole("button", { name: "下一週" }));
  await waitFor(() => expect(api.calls.some((call) => call.params.get("from") === "2026-11-23T00:00")).toBe(true));
  expect(screen.getByTestId("location").textContent).toContain("week=2026-11-23");
});

test("testCrossDayBookingShowsBothDates", async () => {
  open({ routes: { "GET /api/booking/bookings": () => ({ body: [{ ...booking, startAt: "2026-11-22T22:00:00", endAt: "2026-11-23T06:00:00" }] }) } });
  expect(await screen.findByText("11/22（日） 22:00 – 11/23（一） 06:00")).toBeInTheDocument();
});

test("testCreateBookingDefaultsOrganizerToSelf", async () => {
  const { api } = open({ routes: { "POST /api/booking/bookings": () => ({ status: 201, body: booking }) } });
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "新增排程" }));
  await fillBasics(user);
  await waitFor(() => expect(screen.getByLabelText("主辦人")).toHaveValue("2"));
  await user.click(screen.getByRole("button", { name: "儲存" }));
  await waitFor(() => expect(api.calls.some((call) => call.method === "POST")).toBe(true));
  expect(api.calls.find((call) => call.method === "POST")?.body).toMatchObject({
    title: "新會議", organizerEmployeeId: 2, startAt: "2026-11-20T10:00", endAt: "2026-11-20T11:00",
  });
});

test("testAdminWithoutEmployeeMustPickOrganizer", async () => {
  const { api } = open({ user: testUser });
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "新增排程" }));
  await fillBasics(user);
  expect(screen.getByLabelText("主辦人")).toHaveValue("");
  await user.click(screen.getByRole("button", { name: "儲存" }));
  expect(await screen.findByText("請選擇主辦人")).toBeInTheDocument();
  expect(api.calls.some((call) => call.method === "POST")).toBe(false);
});

test("testResourceConflictListsClashAndHasNoOverride", async () => {
  open({
    routes: {
      "POST /api/booking/bookings": () => conflictError("RESOURCE_CONFLICT", "資源在這個時段已被預約", [
        { bookingId: 7, title: "團隊週會", startAt: "2026-11-20T10:00:00", endAt: "2026-11-20T11:00:00", resourceId: 1, resourceName: "3F 大會議室" },
      ]),
    },
  });
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "新增排程" }));
  await fillBasics(user);
  await user.click(screen.getByRole("button", { name: "儲存" }));
  const alert = await screen.findByRole("alert");
  expect(within(alert).getByText(/3F 大會議室/)).toBeInTheDocument();
  expect(within(alert).getByText(/團隊週會/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "仍要排" })).toBeNull();
});

test("testParticipantWarningCanBeOverridden", async () => {
  let attempts = 0;
  const { api } = open({
    routes: {
      "POST /api/booking/bookings": () => {
        attempts += 1;
        return attempts === 1
          ? conflictError("PARTICIPANT_CONFLICT", "有參加者在這個時段不方便", [{ employeeId: 3, name: "黃志強", reason: "同時段已有其他排程" }])
          : { status: 201, body: booking };
      },
    },
  });
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "新增排程" }));
  await fillBasics(user);
  await user.click(screen.getByRole("button", { name: "儲存" }));
  expect(await screen.findByText(/同時段已有其他排程/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "仍要排" }));
  await waitFor(() => expect(api.calls.filter((call) => call.method === "POST")).toHaveLength(2));
  const [first, second] = api.calls.filter((call) => call.method === "POST").map((call) => call.body as Record<string, unknown>);
  expect(first.acknowledgeWarnings).toBe(false);
  expect(second).toEqual({ ...first, acknowledgeWarnings: true });
  await waitFor(() => expect(screen.queryByLabelText("標題")).toBeNull());
});

test("testEditAndCancelOnlyForCreatorOrWriteAny", async () => {
  const others = { ...booking, createdBy: 99 };
  const routes = { "GET /api/booking/bookings": () => ({ body: [others] }) };
  const first = open({ routes });
  await userEvent.setup().click(await screen.findByText("團隊週會"));
  expect(await screen.findByText("備註", { selector: "dt" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "編輯" })).toBeNull();
  expect(screen.queryByRole("button", { name: "取消排程" })).toBeNull();
  first.unmount();

  open({ routes, permissions: [...base, "booking.writeAny"] });
  await userEvent.setup().click(await screen.findByText("團隊週會"));
  expect(await screen.findByRole("button", { name: "編輯" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "取消排程" })).toBeInTheDocument();
});

test("testCancelClosesDrawerWhenRowDisappears", async () => {
  let cancelled = false;
  const { api } = open({
    routes: {
      "GET /api/booking/bookings": () => ({ body: cancelled ? [] : [booking] }),
      "POST /api/booking/bookings/7/cancel": () => { cancelled = true; return { body: { ...booking, status: "cancelled" } }; },
    },
  });
  const user = userEvent.setup();
  await user.click(await screen.findByText("團隊週會"));
  await user.click(await screen.findByRole("button", { name: "取消排程" }));
  expect(api.calls.some((call) => call.method === "POST")).toBe(false);
  await user.click(screen.getByRole("button", { name: "確定取消？" }));
  await waitFor(() => expect(api.calls.some((call) => call.path === "/api/booking/bookings/7/cancel")).toBe(true));
  await waitFor(() => expect(screen.queryByText("備註", { selector: "dt" })).toBeNull());
  expect(screen.getByTestId("location").textContent).not.toContain("id=7");
});

test("testEditSendsOnlyChangedFields", async () => {
  const { api } = open({ routes: { "PATCH /api/booking/bookings/7": () => ({ body: booking }) } });
  const user = userEvent.setup();
  await user.click(await screen.findByText("團隊週會"));
  await user.click(await screen.findByRole("button", { name: "編輯" }));
  const title = screen.getByLabelText("標題");
  await user.clear(title);
  await user.type(title, "改過的標題");
  await user.click(screen.getByRole("button", { name: "儲存" }));
  await waitFor(() => expect(api.calls.some((call) => call.method === "PATCH")).toBe(true));
  expect(api.calls.find((call) => call.method === "PATCH")?.body).toEqual({ title: "改過的標題" });
});

test("testDoubleClickOnCancelDoesNotSkipConfirmation", async () => {
  const { api } = open({ routes: { "POST /api/booking/bookings/7/cancel": () => ({ body: booking }) } });
  const user = userEvent.setup();
  await user.click(await screen.findByText("團隊週會"));
  await user.dblClick(await screen.findByRole("button", { name: "取消排程" }));
  expect(api.calls.some((call) => call.path.endsWith("/cancel"))).toBe(false);
  expect(screen.getByRole("button", { name: "確定取消？" })).toBeInTheDocument();
});

const prefillRoute = (query: string) => `/bookings?week=2026-11-20&new=1&${query}`;

test("testPrefillFromTimelineFillsNewForm", async () => {
  open({ route: prefillRoute("resourceId=1&startAt=2026-11-20T14:00&endAt=2026-11-20T14:30") });
  expect(await screen.findByLabelText("開始")).toHaveValue("2026-11-20T14:00");
  expect(screen.getByLabelText("結束")).toHaveValue("2026-11-20T14:30");
  await waitFor(() => expect(screen.getByRole("checkbox", { name: "3F 大會議室" })).toBeChecked());
});

test("testInvalidPrefillFallsBackToDefaults", async () => {
  const { api } = open({
    route: prefillRoute("resourceId=99&startAt=2026-11-20T15:00&endAt=2026-11-20T14:00"),
    routes: { "POST /api/booking/bookings": () => ({ status: 201, body: booking }) },
  });
  expect(await screen.findByLabelText("開始")).toHaveValue("2026-11-20T10:00");
  expect(screen.getByLabelText("結束")).toHaveValue("2026-11-20T11:00");
  const user = userEvent.setup();
  await fillBasics(user);
  // 資源清單載入後，不在啟用清單裡的 99 要被拿掉，不能偷偷送出畫面上看不到的資源
  expect(await screen.findByRole("checkbox", { name: "3F 大會議室" })).not.toBeChecked();
  await waitFor(() => expect(screen.getByLabelText("主辦人")).toHaveValue("2"));
  await user.click(screen.getByRole("button", { name: "儲存" }));
  await waitFor(() => expect(api.calls.some((call) => call.method === "POST")).toBe(true));
  expect(api.calls.find((call) => call.method === "POST")?.body).toMatchObject({ resourceIds: [] });
});

test("testClosingPrefilledFormClearsUrl", async () => {
  open({ route: prefillRoute("resourceId=1&startAt=2026-11-20T14:00&endAt=2026-11-20T15:00") });
  await userEvent.setup().click(await screen.findByRole("button", { name: "取消" }));
  const location = screen.getByTestId("location").textContent ?? "";
  expect(location).toContain("week=2026-11-20");
  expect(location).not.toContain("new=");
  expect(location).not.toContain("resourceId");
  expect(location).not.toContain("startAt");
  expect(location).not.toContain("endAt");
});
