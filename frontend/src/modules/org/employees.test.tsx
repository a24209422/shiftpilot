import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Department, Employee } from "../../api/types";
import type { MockRoutes } from "../../test/mockApi";
import { renderApp } from "../../test/renderApp";
import { orgRegistration } from "./index";

const engineering: Department = { id: 1, name: "工程部", parentId: null };
const boss: Employee = { id: 1, employeeNo: "E001", name: "陳大文", email: null, departmentId: 1, jobTitle: "經理", managerId: null, hiredOn: "2020-03-01", isActive: true, leftOn: null };
const staff: Employee = { id: 2, employeeNo: "E002", name: "林小美", email: null, departmentId: 1, jobTitle: "工程師", managerId: 1, hiredOn: "2021-07-15", isActive: true, leftOn: null };
const gone: Employee = { id: 3, employeeNo: "E003", name: "離職者", email: null, departmentId: 1, jobTitle: "工程師", managerId: null, hiredOn: "2019-01-01", isActive: false, leftOn: "2025-12-31" };
const manage = ["org.read", "org.manage"];

const open = (permissions: string[], routes: MockRoutes = {}) =>
  renderApp({
    route: "/employees", permissions, registrations: [orgRegistration],
    routes: {
      "GET /api/org/departments": () => ({ body: [engineering] }),
      "GET /api/org/employees": () => ({ body: [boss, staff, gone] }),
      ...routes,
    },
  });

test("testListShowsDepartmentAndManagerNames", async () => {
  open(["org.read"]);
  const row = (await screen.findByText("林小美")).closest("tr")!;
  expect(within(row).getByText("工程部")).toBeInTheDocument();
  expect(within(row).getByText("陳大文")).toBeInTheDocument();
  expect(screen.queryByText("離職者")).toBeNull();
});

test("testCreateEmployeeSendsDates", async () => {
  const { api } = open(manage, { "POST /api/org/employees": () => ({ status: 201, body: boss }) });
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "新增員工" }));
  await user.type(screen.getByLabelText("員工編號"), "E009");
  await user.type(screen.getByLabelText("姓名"), "新同事");
  await user.selectOptions(screen.getByLabelText("部門"), "1");
  await user.type(screen.getByLabelText("職稱"), "工程師");
  await user.type(screen.getByLabelText("到職日"), "2026-11-20");
  await user.click(screen.getByRole("button", { name: "儲存" }));
  await waitFor(() => expect(api.calls.find((call) => call.method === "POST")?.body).toEqual({
    employeeNo: "E009", name: "新同事", email: null, departmentId: 1, jobTitle: "工程師", managerId: null, hiredOn: "2026-11-20",
  }));
});

test("testDeactivateSendsLeftOn", async () => {
  const { api } = open(manage, { "PATCH /api/org/employees/2": () => ({ body: staff }) });
  const user = userEvent.setup();
  await user.click(await screen.findByText("林小美"));
  await user.click(await screen.findByRole("button", { name: "停用" }));
  const date = screen.getByLabelText("離職日");
  await user.clear(date);
  await user.type(date, "2026-11-30");
  await user.click(screen.getByRole("button", { name: "確定停用" }));
  await waitFor(() => expect(api.calls.find((call) => call.method === "PATCH")?.body).toEqual({ isActive: false, leftOn: "2026-11-30" }));
});

test("testReactivateClearsLeftOn", async () => {
  const { api } = open(manage, { "PATCH /api/org/employees/3": () => ({ body: gone }) });
  const user = userEvent.setup();
  await user.click(await screen.findByLabelText("含已停用"));
  await user.click(await screen.findByText("離職者"));
  await user.click(await screen.findByRole("button", { name: "重新啟用" }));
  await waitFor(() => expect(api.calls.find((call) => call.method === "PATCH")?.body).toEqual({ isActive: true, leftOn: null }));
});

test("testManagerOptionsExcludeSelfAndInactive", async () => {
  open(manage);
  const user = userEvent.setup();
  await user.click(await screen.findByText("林小美"));
  await user.click(await screen.findByRole("button", { name: "編輯" }));
  const options = within(screen.getByLabelText("主管")).getAllByRole("option").map((item) => item.textContent);
  expect(options).toEqual(["（無）", "陳大文"]);
});

test("testDeactivateConfirmationDoesNotCarryToAnotherEmployee", async () => {
  const { api } = open(manage);
  const user = userEvent.setup();
  await user.click(await screen.findByText("林小美"));
  await user.click(await screen.findByRole("button", { name: "停用" }));
  expect(screen.getByRole("button", { name: "確定停用" })).toBeInTheDocument();
  await user.click((await screen.findAllByText("陳大文"))[0]);
  expect(screen.queryByRole("button", { name: "確定停用" })).toBeNull();
  expect(await screen.findByRole("button", { name: "停用" })).toBeInTheDocument();
  expect(api.calls.some((call) => call.method === "PATCH")).toBe(false);
});
