import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Employee, LeaveBalance, LeaveType } from "../../api/types";
import type { MockRoutes } from "../../test/mockApi";
import { renderApp, testUser } from "../../test/renderApp";
import { leaveRegistration } from "./index";

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(2026, 10, 20, 9, 30));
});
afterEach(() => vi.useRealTimers());

const types: LeaveType[] = [
  { id: 1, code: "annual", name: "特休", paidRatio: 1, quotaKind: "seniority", annualCapHours: null, isActive: true },
  { id: 2, code: "personal", name: "事假", paidRatio: 0, quotaKind: "yearly_cap", annualCapHours: 112, isActive: true },
  { id: 7, code: "bereavement", name: "喪假", paidRatio: 1, quotaKind: "none", annualCapHours: null, isActive: true },
];
const employee: Employee = { id: 2, employeeNo: "E002", name: "林小美", email: null, departmentId: 1, jobTitle: "工程師", managerId: null, hiredOn: "2025-01-01", isActive: true, leftOn: null };
const balances: LeaveBalance[] = [
  { leaveTypeId: 1, leaveTypeName: "特休", quotaKind: "seniority", periodStart: "2026-01-01", periodEnd: "2026-12-31", quotaHours: 56, adjustmentHours: 0, approvedHours: 0, pendingHours: 0, remainingHours: 56 },
  { leaveTypeId: 2, leaveTypeName: "事假", quotaKind: "yearly_cap", periodStart: "2026-01-01", periodEnd: "2026-12-31", quotaHours: 112, adjustmentHours: 0, approvedHours: 0, pendingHours: 0, remainingHours: 112 },
];

const open = (route: string, routes: MockRoutes = {}) =>
  renderApp({
    route, user: { ...testUser, role: "hr" }, permissions: ["leave.request", "leave.manage", "org.read"], registrations: [leaveRegistration],
    routes: {
      "GET /api/leave/types": () => ({ body: types }),
      "GET /api/org/employees": () => ({ body: [employee] }),
      "GET /api/leave/balances": () => ({ body: balances }),
      "GET /api/leave/adjustments": () => ({ body: [] }),
      "GET /api/leave/unused": () => ({ body: [] }),
      ...routes,
    },
  });

test("testTypesTabListsAllIncludingInactive", async () => {
  const { api } = open("/leave/admin");
  expect(await screen.findByText("事假")).toBeInTheDocument();
  expect(api.calls.find((call) => call.path === "/api/leave/types")!.params.get("includeInactive")).toBe("true");
});

test("testCreateYearlyCapTypeSendsCapHours", async () => {
  const { api } = open("/leave/admin", { "POST /api/leave/types": () => ({ status: 201, body: { ...types[1], id: 10 } }) });
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "新增假別" }));
  await user.type(screen.getByLabelText("代碼"), "family");
  await user.type(screen.getByLabelText("名稱"), "家庭照顧假");
  await user.selectOptions(screen.getByLabelText("額度類型"), "yearly_cap");
  await user.type(screen.getByLabelText("年度上限（小時）"), "56");
  await user.click(screen.getByRole("button", { name: "儲存" }));
  await waitFor(() => expect(api.calls.find((call) => call.method === "POST")?.body).toEqual({
    code: "family", name: "家庭照顧假", paidRatio: 1, quotaKind: "yearly_cap", annualCapHours: 56,
  }));
});

test("testDeactivateType", async () => {
  const { api } = open("/leave/admin", { "PATCH /api/leave/types/2": () => ({ body: { ...types[1], isActive: false } }) });
  const user = userEvent.setup();
  await user.click(await screen.findByText("事假"));
  await user.click(await screen.findByRole("button", { name: "停用" }));
  await waitFor(() => expect(api.calls.find((call) => call.method === "PATCH")?.body).toEqual({ isActive: false }));
});

test("testAdjustmentPrefillsPeriodStartFromBalance", async () => {
  const { api } = open("/leave/admin?tab=adjustments", { "POST /api/leave/adjustments": () => ({ status: 201, body: {} }) });
  const user = userEvent.setup();
  // 員工清單是非同步載入，要等選項出現才能選
  await screen.findByRole("option", { name: /林小美/ });
  await user.selectOptions(screen.getByLabelText("員工"), "2");
  await user.click(screen.getByRole("button", { name: "新增調整" }));
  await user.selectOptions(await screen.findByLabelText("假別"), "1");
  await waitFor(() => expect(screen.getByLabelText("年度開始日")).toHaveValue("2026-01-01"));
  expect(screen.queryByRole("option", { name: "喪假" })).not.toBeInTheDocument();
  await user.type(screen.getByLabelText("時數"), "-8");
  await user.type(screen.getByLabelText("原因"), "更正");
  await user.click(screen.getByRole("button", { name: "儲存" }));
  await waitFor(() => expect(api.calls.find((call) => call.method === "POST")?.body).toEqual({
    employeeId: 2, leaveTypeId: 1, periodStart: "2026-01-01", hours: -8, reason: "更正",
  }));
});

test("testAdjustmentClearsPeriodStartWhenTypeHasNoPeriod", async () => {
  // 事假沒有年度（餘額裡沒有這個假別）：切過去後日期要清空，不能留著特休的日期
  open("/leave/admin?tab=adjustments", { "GET /api/leave/balances": () => ({ body: [balances[0]] }) });
  const user = userEvent.setup();
  await screen.findByRole("option", { name: /林小美/ });
  await user.selectOptions(screen.getByLabelText("員工"), "2");
  await user.click(screen.getByRole("button", { name: "新增調整" }));
  await user.selectOptions(await screen.findByLabelText("假別"), "1");
  await waitFor(() => expect(screen.getByLabelText("年度開始日")).toHaveValue("2026-01-01"));
  await user.selectOptions(screen.getByLabelText("假別"), "2");
  await waitFor(() => expect(screen.getByLabelText("年度開始日")).toHaveValue(""));
  await user.type(screen.getByLabelText("年度開始日"), "2025-01-01");
  expect(screen.getByLabelText("年度開始日")).toHaveValue("2025-01-01");
});

test("testUnusedReportQueriesRange", async () => {
  const { api } = open("/leave/admin?tab=unused", {
    "GET /api/leave/unused": () => ({ body: [{ employeeId: 2, employeeName: "林小美", departmentName: "工程部", periodStart: "2025-07-01", periodEnd: "2025-12-31", quotaHours: 24, adjustmentHours: 0, usedHours: 8, unusedHours: 16 }] }),
  });
  expect(await screen.findByText("16 小時")).toBeInTheDocument();
  const call = api.calls.find((item) => item.path === "/api/leave/unused")!;
  expect(call.params.get("periodEndFrom")).toBe("2026-01-01");
  expect(call.params.get("periodEndTo")).toBe("2026-11-20");
});
