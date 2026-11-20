import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Employee, User } from "../../api/types";
import type { MockRoutes } from "../../test/mockApi";
import { renderApp } from "../../test/renderApp";
import { coreRegistration } from "./index";

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(2026, 10, 20, 9, 30));
});
afterEach(() => vi.useRealTimers());

const user = (id: number, email: string, extra: Partial<User> = {}): User => ({
  id, email, role: "employee", employeeId: null, employeeName: null, isActive: true, lastLoginAt: null, lockedUntil: null, createdAt: "2026-11-01T08:00:00", ...extra,
});
const employee = (id: number, name: string): Employee => ({
  id, employeeNo: `E00${id}`, name, email: null, departmentId: 1, jobTitle: "工程師", managerId: null, hiredOn: "2024-01-01", isActive: true, leftOn: null,
});
const adminPermissions = ["core.users.manage", "core.audit.read"];
const users = [
  user(1, "admin@example.com", { role: "admin" }),
  user(2, "lin@example.com", { role: "manager", employeeId: 2, employeeName: "林小美", lastLoginAt: "2026-11-19T17:30:00" }),
  user(3, "locked@example.com", { lockedUntil: "2026-11-20T10:00:00" }),
  user(4, "off@example.com", { isActive: false }),
];

const open = (routes: MockRoutes = {}, permissions = adminPermissions, route = "/users") =>
  renderApp({
    route, permissions, registrations: [coreRegistration],
    routes: {
      "GET /api/core/users": () => ({ body: users }),
      "GET /api/org/employees": () => ({ body: [employee(2, "林小美"), employee(3, "黃志強")] }),
      ...routes,
    },
  });

test("testListShowsRoleLabelsAndLockState", async () => {
  open();
  const linRow = (await screen.findByText("lin@example.com")).closest("tr")!;
  expect(within(linRow).getByText("主管")).toBeInTheDocument();
  expect(within(linRow).getByText("林小美")).toBeInTheDocument();
  const lockedRow = screen.getByText("locked@example.com").closest("tr")!;
  expect(within(lockedRow).getByText("鎖定中")).toBeInTheDocument();
  expect(within(lockedRow).getByText("從未")).toBeInTheDocument();
  expect(within(screen.getByText("off@example.com").closest("tr")!).getByText("已停用")).toBeInTheDocument();
});

test("testCreateUserValidatesPasswordLength", async () => {
  const { api } = open();
  const ui = userEvent.setup();
  await ui.click(await screen.findByRole("button", { name: "新增帳號" }));
  await ui.type(screen.getByLabelText("Email"), "new@example.com");
  await ui.type(screen.getByLabelText("密碼"), "short12");
  await ui.click(screen.getByRole("button", { name: "儲存" }));
  expect(await screen.findByText("密碼要 8 到 128 字元")).toBeInTheDocument();
  expect(api.calls.some((call) => call.method === "POST")).toBe(false);
});

test("testCreateUserSendsEmployeeLink", async () => {
  const { api } = open({ "POST /api/core/users": () => ({ status: 201, body: user(9, "new@example.com") }) });
  const ui = userEvent.setup();
  await ui.click(await screen.findByRole("button", { name: "新增帳號" }));
  await ui.type(screen.getByLabelText("Email"), "new@example.com");
  await ui.type(screen.getByLabelText("密碼"), "password123");
  await waitFor(() => expect(within(screen.getByLabelText("連結員工")).getAllByRole("option").length).toBeGreaterThan(1));
  await ui.selectOptions(screen.getByLabelText("連結員工"), "3");
  await ui.click(screen.getByRole("button", { name: "儲存" }));
  await waitFor(() => expect(api.calls.find((call) => call.method === "POST")?.body).toEqual({
    email: "new@example.com", password: "password123", role: "employee", employeeId: 3,
  }));
});

test("testEmployeeOptionsExcludeLinkedEmployees", async () => {
  open();
  await userEvent.setup().click(await screen.findByRole("button", { name: "新增帳號" }));
  await waitFor(() => expect(within(screen.getByLabelText("連結員工")).getAllByRole("option").length).toBeGreaterThan(1));
  const options = within(screen.getByLabelText("連結員工")).getAllByRole("option").map((item) => item.textContent);
  expect(options).toEqual(["（不連結）", "黃志強"]);
});

test("testResetPasswordUsesPost", async () => {
  const { api } = open({ "POST /api/core/users/2/password": () => ({ status: 204 }) });
  const ui = userEvent.setup();
  await ui.click(await screen.findByText("lin@example.com"));
  await ui.click(await screen.findByRole("button", { name: "重設密碼" }));
  await ui.type(screen.getByLabelText("新密碼"), "brand-new-pass");
  await ui.type(screen.getByLabelText("再輸入一次新密碼"), "brand-new-pass");
  await ui.click(screen.getByRole("button", { name: "確定重設" }));
  await waitFor(() => expect(api.calls.find((call) => call.method === "POST")?.body).toEqual({ newPassword: "brand-new-pass" }));
});

test("testCannotModifySelfMessageShown", async () => {
  open({ "PATCH /api/core/users/1": () => ({ status: 422, body: { error: { code: "CANNOT_MODIFY_SELF", message: "不能修改自己的帳號", details: null } } }) });
  const ui = userEvent.setup();
  await ui.click(await screen.findByText("admin@example.com"));
  await ui.click(await screen.findByRole("button", { name: "編輯" }));
  await ui.selectOptions(screen.getByLabelText("角色"), "employee");
  await ui.click(screen.getByRole("button", { name: "儲存" }));
  expect(await screen.findByText("不能修改自己的帳號")).toBeInTheDocument();
});

test("testNonAdminCannotSeeAccountsOrAudit", async () => {
  open({}, ["org.read", "org.manage", "booking.read", "booking.write", "booking.writeAny"], "/users");
  expect(await screen.findByText("沒有權限看這個頁面")).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /帳號/ })).toBeNull();
  expect(screen.queryByRole("link", { name: /稽核/ })).toBeNull();
});
