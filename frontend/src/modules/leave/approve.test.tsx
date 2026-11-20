import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { MockRoutes } from "../../test/mockApi";
import { renderApp, testUser } from "../../test/renderApp";
import { leaveRequest } from "./fixtures";
import { leaveRegistration } from "./index";

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(2026, 10, 20, 9, 30));
});
afterEach(() => vi.useRealTimers());

const boss = { ...testUser, role: "manager" as const, employeeId: 1, employeeName: "陳主管" };
const pending = leaveRequest();

const open = (options: { toApprove?: unknown[]; user?: typeof testUser; permissions?: string[]; route?: string; routes?: MockRoutes } = {}) =>
  renderApp({
    route: options.route ?? "/leave", user: options.user ?? boss, permissions: options.permissions ?? ["leave.request"], registrations: [leaveRegistration],
    routes: {
      "GET /api/leave/balances": () => ({ body: [] }),
      "GET /api/leave/requests": ({ params }) => ({ body: params.get("scope") === "toApprove" ? (options.toApprove ?? [pending]) : [] }),
      "GET /api/leave/requests/5": () => ({ body: pending }),
      ...options.routes,
    },
  });

test("testApproveTabAppearsOnlyWithPendingItems", async () => {
  open();
  expect(await screen.findByRole("tab", { name: "待我核准" })).toBeInTheDocument();
});

test("testApproveTabHiddenWhenNothingToApprove", async () => {
  open({ toApprove: [] });
  await screen.findByRole("tab", { name: "我的申請" });
  expect(screen.queryByRole("tab", { name: "待我核准" })).not.toBeInTheDocument();
});

test("testHrAlwaysSeesApproveTab", async () => {
  open({ toApprove: [], permissions: ["leave.request", "leave.manage"] });
  expect(await screen.findByRole("tab", { name: "待我核准" })).toBeInTheDocument();
});

test("testApproveSendsNote", async () => {
  const { api } = open({ route: "/leave?tab=approve", routes: { "POST /api/leave/requests/5/approve": () => ({ body: { ...pending, status: "approved" } }) } });
  const user = userEvent.setup();
  await user.click(await screen.findByText("林小美"));
  await user.type(await screen.findByLabelText("核准備註或退回理由"), "OK");
  await user.click(screen.getByRole("button", { name: "核准" }));
  await waitFor(() => expect(api.calls.find((call) => call.path === "/api/leave/requests/5/approve")?.body).toEqual({ note: "OK" }));
});

test("testRejectRequiresNote", async () => {
  const { api } = open({ route: "/leave?tab=approve&id=5" });
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "退回" }));
  expect(await screen.findByText("退回要填理由")).toBeInTheDocument();
  expect(api.calls.some((call) => call.path === "/api/leave/requests/5/reject")).toBe(false);
});

const hr = { ...testUser, role: "hr" as const, employeeId: 9, employeeName: "人資" };

test("testHrCanDecideRequestNotInToApprove", async () => {
  open({ route: "/leave?id=5", toApprove: [], user: hr, permissions: ["leave.request", "leave.manage"] });
  expect(await screen.findByRole("button", { name: "核准" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "退回" })).toBeInTheDocument();
});

test("testHrCannotDecideOwnRequest", async () => {
  open({
    route: "/leave?id=5", toApprove: [], user: { ...hr, employeeId: 2 }, permissions: ["leave.request", "leave.manage"],
    routes: { "GET /api/leave/requests/5": () => ({ body: pending }) },
  });
  await screen.findByText("林小美");
  expect(screen.queryByRole("button", { name: "核准" })).not.toBeInTheDocument();
});
