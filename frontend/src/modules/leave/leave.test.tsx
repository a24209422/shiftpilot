import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { LeaveBalance, LeaveType } from "../../api/types";
import type { MockRoutes } from "../../test/mockApi";
import { renderApp, testUser } from "../../test/renderApp";
import { leaveRequest } from "./fixtures";
import { leaveRegistration } from "./index";

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(2026, 10, 20, 9, 30));
});
afterEach(() => vi.useRealTimers());

const alice = { ...testUser, role: "employee" as const, employeeId: 2, employeeName: "林小美" };
const types: LeaveType[] = [
  { id: 1, code: "annual", name: "特休", paidRatio: 1, quotaKind: "seniority", annualCapHours: null, isActive: true },
  { id: 2, code: "personal", name: "事假", paidRatio: 0, quotaKind: "yearly_cap", annualCapHours: 112, isActive: true },
  { id: 7, code: "bereavement", name: "喪假", paidRatio: 1, quotaKind: "none", annualCapHours: null, isActive: true },
];
const balances: LeaveBalance[] = [
  { leaveTypeId: 1, leaveTypeName: "特休", quotaKind: "seniority", periodStart: "2026-01-01", periodEnd: "2026-12-31", quotaHours: 56, adjustmentHours: 0, approvedHours: 8, pendingHours: 4, remainingHours: 44 },
  { leaveTypeId: 2, leaveTypeName: "事假", quotaKind: "yearly_cap", periodStart: "2026-01-01", periodEnd: "2026-12-31", quotaHours: 112, adjustmentHours: 0, approvedHours: 0, pendingHours: 0, remainingHours: 112 },
  { leaveTypeId: 7, leaveTypeName: "喪假", quotaKind: "none", periodStart: "2026-01-01", periodEnd: "2026-12-31", quotaHours: null, adjustmentHours: 0, approvedHours: 0, pendingHours: 0, remainingHours: null },
];
// 外殼右側的問答面板也有一顆「送出」（aria-label），所以表單的送出鈕要限定在詳情面板內找
const drawerSubmit = () => within(screen.getByRole("complementary", { name: "詳情" })).getByRole("button", { name: "送出" });
const open = (routes: MockRoutes = {}, route = "/leave") =>
  renderApp({
    route, user: alice, permissions: ["leave.request"], registrations: [leaveRegistration],
    routes: {
      "GET /api/leave/types": () => ({ body: types }),
      "GET /api/leave/balances": () => ({ body: balances }),
      "GET /api/leave/requests": ({ params }) => ({ body: params.get("scope") === "mine" ? [leaveRequest()] : [] }),
      "GET /api/leave/requests/5": () => ({ body: leaveRequest() }),
      ...routes,
    },
  });

test("testBalanceCardsShowRemainingAndUnlimited", async () => {
  open();
  expect(await screen.findByText("剩 44 小時")).toBeInTheDocument();
  expect(screen.getByText("已用 8 ／ 待核准 4")).toBeInTheDocument();
  expect(screen.getByText("年度 2026-01-01 – 2026-12-31")).toBeInTheDocument();
  expect(screen.getByText("不限")).toBeInTheDocument();
});

test("testMyRequestsListedAndWithdrawable", async () => {
  const { api } = open({ "POST /api/leave/requests/5/withdraw": () => ({ body: leaveRequest({ status: "withdrawn" }) }) });
  const user = userEvent.setup();
  await user.click(await screen.findByText("家裡有事"));
  const withdraw = await screen.findByRole("button", { name: "撤回" });
  await user.click(withdraw);
  await user.click(screen.getByRole("button", { name: "確定撤回？" }));
  await waitFor(() => expect(api.calls.some((call) => call.method === "POST" && call.path === "/api/leave/requests/5/withdraw")).toBe(true));
});

test("testApprovedFutureLeaveCanBeCancelledButStartedCannot", async () => {
  open({ "GET /api/leave/requests/5": () => ({ body: leaveRequest({ status: "approved" }) }) }, "/leave?id=5");
  expect(await screen.findByRole("button", { name: "取消請假" })).toBeInTheDocument();
});

test("testStartedLeaveHasNoCancelForEmployee", async () => {
  open({ "GET /api/leave/requests/5": () => ({ body: leaveRequest({ status: "approved", startAt: "2026-11-20T09:00:00" }) }) }, "/leave?id=5");
  await screen.findByText("家裡有事", { selector: "dd" });
  expect(screen.queryByRole("button", { name: "取消請假" })).not.toBeInTheDocument();
});

test("testFormQuotesHoursAndSubmits", async () => {
  const { api } = open({
    "POST /api/leave/requests/quote": () => ({ body: { hours: 8, remainingAfter: 36, conflicts: [] } }),
    "POST /api/leave/requests": () => ({ status: 201, body: leaveRequest({ id: 6 }) }),
  });
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "申請請假" }));
  await user.selectOptions(await screen.findByLabelText("假別"), "1");
  expect(await screen.findByText("共 8 小時，送出後剩 36 小時")).toBeInTheDocument();
  const quote = api.calls.find((call) => call.path === "/api/leave/requests/quote")!;
  expect(quote.body).toMatchObject({ leaveTypeId: 1, startAt: "2026-11-21T09:00", endAt: "2026-11-21T18:00" });
  await user.type(screen.getByLabelText("事由"), "回診");
  await user.click(drawerSubmit());
  await waitFor(() => expect(api.calls.some((call) => call.method === "POST" && call.path === "/api/leave/requests")).toBe(true));
  expect(api.calls.find((call) => call.method === "POST" && call.path === "/api/leave/requests")!.body).toMatchObject({ reason: "回診", acknowledgeWarnings: false });
});

test("testQuotaErrorDisablesSubmit", async () => {
  open({
    "POST /api/leave/requests/quote": () => ({ status: 422, body: { error: { code: "LEAVE_QUOTA_EXCEEDED", message: "特休只剩 4 小時，這次要 8 小時", details: { remainingHours: 4 } } } }),
  });
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "申請請假" }));
  await user.selectOptions(await screen.findByLabelText("假別"), "1");
  expect(await screen.findByText("特休只剩 4 小時，這次要 8 小時")).toBeInTheDocument();
  expect(drawerSubmit()).toBeDisabled();
});

test("testMeetingConflictCanBeOverridden", async () => {
  let attempts = 0;
  const { api } = open({
    "POST /api/leave/requests/quote": () => ({ body: { hours: 8, remainingAfter: 36, conflicts: [] } }),
    "POST /api/leave/requests": () => {
      attempts += 1;
      if (attempts === 1) {
        return { status: 409, body: { error: { code: "MEETING_CONFLICT", message: "這段時間你有會議", details: { conflicts: [{ bookingId: 3, title: "週會", startAt: "2026-11-21T10:00:00", endAt: "2026-11-21T11:00:00" }] } } } };
      }
      return { status: 201, body: leaveRequest({ id: 6 }) };
    },
  });
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "申請請假" }));
  await user.selectOptions(await screen.findByLabelText("假別"), "1");
  await screen.findByText("共 8 小時，送出後剩 36 小時");
  await user.click(drawerSubmit());
  expect(await screen.findByText(/週會/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "仍要送出" }));
  await waitFor(() => expect(attempts).toBe(2));
  const last = api.calls.filter((call) => call.method === "POST" && call.path === "/api/leave/requests").at(-1)!;
  expect(last.body).toMatchObject({ acknowledgeWarnings: true });
});

test("testEditedFormDropsMeetingOverride", async () => {
  const { api } = open({
    "POST /api/leave/requests/quote": () => ({ body: { hours: 8, remainingAfter: 36, conflicts: [] } }),
    "POST /api/leave/requests": () => ({ status: 409, body: { error: { code: "MEETING_CONFLICT", message: "這段時間你有會議", details: { conflicts: [{ bookingId: 3, title: "週會", startAt: "2026-11-21T10:00:00", endAt: "2026-11-21T11:00:00" }] } } } }),
  });
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "申請請假" }));
  await user.selectOptions(await screen.findByLabelText("假別"), "1");
  await screen.findByText("共 8 小時，送出後剩 36 小時");
  await user.click(drawerSubmit());
  await screen.findByRole("button", { name: "仍要送出" });
  await user.selectOptions(screen.getByLabelText("結束時間"), "17:00");
  expect(screen.queryByRole("button", { name: "仍要送出" })).not.toBeInTheDocument();
  expect(api.calls.filter((call) => call.method === "POST" && call.path === "/api/leave/requests")).toHaveLength(1);
});

test("testAccountWithoutEmployeeSeesExplanation", async () => {
  renderApp({ route: "/leave", user: testUser, permissions: ["leave.request"], registrations: [leaveRegistration], routes: { "GET /api/leave/requests": () => ({ body: [] }) } });
  expect(await screen.findByText("這個帳號沒有對應的員工，不能請假")).toBeInTheDocument();
});

test("testDecidedAtShowsSingleTime", async () => {
  open({ "GET /api/leave/requests/5": () => ({ body: leaveRequest({ status: "approved", decidedAt: "2026-11-21T12:40:00", decidedByName: "陳大文" }) }) }, "/leave?id=5");
  expect(await screen.findByText("11/21（六） 12:40", { selector: "dd" })).toBeInTheDocument();
});

test("testQuoteMeetingTitlesAreDeduplicated", async () => {
  const meeting = (bookingId: number) => ({ bookingId, title: "晨會", startAt: "2026-11-21T09:00:00", endAt: "2026-11-21T10:00:00" });
  open({ "POST /api/leave/requests/quote": () => ({ body: { hours: 8, remainingAfter: 36, conflicts: [meeting(1), meeting(2)] } }) });
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "申請請假" }));
  await user.selectOptions(await screen.findByLabelText("假別"), "1");
  expect(await screen.findByText("這段時間你有會議：晨會")).toBeInTheDocument();
});
