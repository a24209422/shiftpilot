import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Employee, ScheduleDay, ShiftType } from "../../api/types";
import type { MockRoutes } from "../../test/mockApi";
import { renderApp, testUser } from "../../test/renderApp";
import { shiftRegistration } from "./index";

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(2026, 10, 20, 9, 30));
});
afterEach(() => vi.useRealTimers());

const employee = (id: number, name: string, managerId: number | null = null): Employee => ({
  id, employeeNo: `E00${id}`, name, email: null, departmentId: 1, jobTitle: "客服", managerId, hiredOn: "2025-01-01", isActive: true, leftOn: null,
});
const evening: ShiftType = { id: 2, code: "evening", name: "晚班", startTime: "14:00", endTime: "23:00", breakStart: "18:00", breakEnd: "19:00", isDefault: false, isActive: true };
const standard: ShiftType = { id: 1, code: "standard", name: "標準班", startTime: "09:00", endTime: "18:00", breakStart: "12:00", breakEnd: "13:00", isDefault: true, isActive: true };

function scheduleFor(employeeId: number, overrides: Partial<Record<string, Partial<ScheduleDay>>> = {}): ScheduleDay[] {
  const days = ["2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20", "2026-11-21", "2026-11-22"];
  return days.map((day, index) => ({
    employeeId, day, source: index < 5 ? "default" : "off", shiftTypeId: index < 5 ? 1 : null, shiftName: index < 5 ? "標準班" : null,
    startAt: index < 5 ? `${day}T09:00:00` : null, endAt: index < 5 ? `${day}T18:00:00` : null,
    breakStartAt: null, breakEndAt: null, holidayName: null, overrideNote: null, ...overrides[day],
  }));
}

const boss = { ...testUser, role: "manager" as const, employeeId: 1, employeeName: "陳主管" };

const open = (options: { user?: typeof testUser; permissions?: string[]; route?: string; routes?: MockRoutes } = {}) =>
  renderApp({
    route: options.route ?? "/shifts", user: options.user ?? boss, permissions: options.permissions ?? ["shift.read", "org.read"],
    registrations: [shiftRegistration],
    routes: {
      "GET /api/org/employees": () => ({ body: [employee(1, "陳主管"), employee(2, "林小美", 1), employee(3, "黃志強")] }),
      "GET /api/org/departments": () => ({ body: [{ id: 1, name: "客服部", parentId: null }] }),
      "GET /api/shift/types": () => ({ body: [standard, evening] }),
      "GET /api/shift/schedule": () => ({ body: [
        ...scheduleFor(1),
        ...scheduleFor(2, { "2026-11-18": { source: "override", shiftTypeId: null, shiftName: null, startAt: null, endAt: null, overrideNote: "補休" } }),
        ...scheduleFor(3, { "2026-11-17": { source: "roster", shiftTypeId: 2, shiftName: "晚班", startAt: "2026-11-17T14:00:00", endAt: "2026-11-17T23:00:00" } }),
      ] }),
      "GET /api/shift/rosters": () => ({ body: [] }),
      ...options.routes,
    },
  });

const cell = (employeeName: string, dayIndex: number) => {
  const row = screen.getByRole("row", { name: new RegExp(employeeName) });
  return within(row).getAllByRole("button")[dayIndex + 1];
};
const drawer = () => within(screen.getByRole("complementary", { name: "詳情" }));

test("testWeekGridShowsCellsAndRequestsWeek", async () => {
  const { api } = open();
  await screen.findByText("黃志強");
  expect(cell("黃志強", 1)).toHaveTextContent("晚班 14–23");
  expect(cell("林小美", 2)).toHaveTextContent("休");
  expect(cell("林小美", 2)).toHaveClass("shiftOverride");
  expect(cell("陳主管", 5)).toHaveTextContent("休");
  const call = api.calls.find((item) => item.path === "/api/shift/schedule")!;
  expect(call.params.get("from")).toBe("2026-11-16");
  expect(call.params.get("to")).toBe("2026-11-22");
});

test("testNextWeekNavigation", async () => {
  const { api } = open();
  await screen.findByText("黃志強");
  await userEvent.setup().click(screen.getByRole("button", { name: "下一週" }));
  await waitFor(() => expect(api.calls.some((item) => item.params.get("from") === "2026-11-23")).toBe(true));
});

test("testManagerCanSetOverrideForSubordinateOnly", async () => {
  const { api } = open({ routes: { "PUT /api/shift/overrides": () => ({ body: {} }) } });
  const user = userEvent.setup();
  await screen.findByText("黃志強");
  await user.click(cell("黃志強", 0));
  expect(drawer().getByText("預設班")).toBeInTheDocument();
  expect(drawer().queryByRole("button", { name: "設定單日調整" })).not.toBeInTheDocument();
  await user.click(cell("林小美", 0));
  await user.selectOptions(await drawer().findByLabelText("班別"), "rest");
  await user.type(drawer().getByLabelText("備註"), "支援");
  await user.click(drawer().getByRole("button", { name: "設定單日調整" }));
  await waitFor(() => expect(api.calls.find((item) => item.method === "PUT")?.body).toEqual({
    employeeId: 2, day: "2026-11-16", shiftTypeId: null, note: "支援",
  }));
});

test("testDeleteOverride", async () => {
  const { api } = open({ routes: { "DELETE /api/shift/overrides/2/2026-11-18": () => ({ status: 204 }) } });
  const user = userEvent.setup();
  await screen.findByText("林小美");
  await user.click(cell("林小美", 2));
  expect(drawer().getByText("補休", { selector: "dd" })).toBeInTheDocument();
  await user.click(drawer().getByRole("button", { name: "刪除調整" }));
  await waitFor(() => expect(api.calls.some((item) => item.method === "DELETE")).toBe(true));
});

test("testEmployeeSeesNoEditButtons", async () => {
  open({ user: { ...testUser, role: "employee", employeeId: 3, employeeName: "黃志強" } });
  const user = userEvent.setup();
  await screen.findByText("林小美");
  await user.click(cell("林小美", 0));
  expect(drawer().queryByRole("button", { name: "設定單日調整" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "林小美" }));
  expect(screen.queryByRole("button", { name: "新增週班表" })).not.toBeInTheDocument();
});

test("testRosterFormSendsWorkingDaysOnly", async () => {
  const { api } = open({ routes: { "POST /api/shift/rosters": () => ({ status: 201, body: {} }) } });
  const user = userEvent.setup();
  await screen.findByText("林小美");
  await user.click(screen.getByRole("button", { name: "林小美" }));
  await user.click(await drawer().findByRole("button", { name: "新增週班表" }));
  const effective = drawer().getByLabelText("生效日");
  await user.clear(effective);
  await user.type(effective, "2026-11-23");
  for (const label of ["週一", "週二", "週三", "週四", "週五"]) await user.selectOptions(drawer().getByLabelText(label), "2");
  await user.click(drawer().getByRole("button", { name: "儲存週班表" }));
  await waitFor(() => expect(api.calls.find((item) => item.method === "POST")?.body).toEqual({
    employeeId: 2, effectiveFrom: "2026-11-23",
    days: [0, 1, 2, 3, 4].map((weekday) => ({ weekday, shiftTypeId: 2 })),
  }));
});

test("testFutureRosterCanBeDeleted", async () => {
  const roster = { id: 7, employeeId: 2, effectiveFrom: "2026-11-30", days: [{ weekday: 0, shiftTypeId: 2, shiftName: "晚班" }], createdBy: 1, createdAt: "2026-11-20T08:00:00" };
  const { api } = open({ routes: { "GET /api/shift/rosters": () => ({ body: [roster] }), "DELETE /api/shift/rosters/7": () => ({ status: 204 }) } });
  const user = userEvent.setup();
  await screen.findByText("林小美");
  await user.click(screen.getByRole("button", { name: "林小美" }));
  expect(await drawer().findByText("週一 晚班")).toBeInTheDocument();
  await user.click(drawer().getByRole("button", { name: "刪除" }));
  await waitFor(() => expect(api.calls.some((item) => item.method === "DELETE" && item.path === "/api/shift/rosters/7")).toBe(true));
});
