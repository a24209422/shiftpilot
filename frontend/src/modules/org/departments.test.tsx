import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Department, Employee } from "../../api/types";
import type { MockRoutes } from "../../test/mockApi";
import { renderApp } from "../../test/renderApp";
import { orgRegistration } from "./index";

const engineering: Department = { id: 1, name: "工程部", parentId: null };
const frontend: Department = { id: 2, name: "前端組", parentId: 1 };
const employee = (id: number, departmentId: number): Employee => ({
  id, employeeNo: `E00${id}`, name: `員工${id}`, email: null, departmentId, jobTitle: "工程師", managerId: null, hiredOn: "2024-01-01", isActive: true, leftOn: null,
});

const open = (permissions: string[], routes: MockRoutes = {}) =>
  renderApp({
    route: "/departments", permissions, registrations: [orgRegistration],
    routes: {
      "GET /api/org/departments": () => ({ body: [engineering, frontend] }),
      "GET /api/org/employees": () => ({ body: [employee(1, 1), employee(2, 1), employee(3, 2)] }),
      ...routes,
    },
  });

test("testDepartmentsListShowsParentName", async () => {
  open(["org.read"]);
  const row = (await screen.findByText("前端組")).closest("tr")!;
  expect(within(row).getByText("工程部")).toBeInTheDocument();
  expect(within(row).getByText("1")).toBeInTheDocument();
});

test("testCreateDepartmentWithParent", async () => {
  const { api } = open(["org.read", "org.manage"], { "POST /api/org/departments": () => ({ status: 201, body: engineering }) });
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "新增部門" }));
  await user.type(screen.getByLabelText("名稱"), "後端組");
  await user.selectOptions(screen.getByLabelText("上層部門"), "1");
  await user.click(screen.getByRole("button", { name: "儲存" }));
  await waitFor(() => expect(api.calls.find((call) => call.method === "POST")?.body).toEqual({ name: "後端組", parentId: 1 }));
});

test("testParentOptionsExcludeSelf", async () => {
  open(["org.read", "org.manage"]);
  const user = userEvent.setup();
  await user.click(await screen.findByText("前端組"));
  await user.click(await screen.findByRole("button", { name: "編輯" }));
  const options = within(screen.getByLabelText("上層部門")).getAllByRole("option").map((item) => item.textContent);
  expect(options).toEqual(["（無）", "工程部"]);
});

test("testCycleErrorShown", async () => {
  open(["org.read", "org.manage"], {
    "PATCH /api/org/departments/1": () => ({ status: 422, body: { error: { code: "DEPARTMENT_CYCLE", message: "部門不能成為自己的下層", details: null } } }),
  });
  const user = userEvent.setup();
  await user.click((await screen.findAllByText("工程部"))[0]);
  await user.click(await screen.findByRole("button", { name: "編輯" }));
  await user.selectOptions(screen.getByLabelText("上層部門"), "2");
  await user.click(screen.getByRole("button", { name: "儲存" }));
  expect(await screen.findByText("部門不能成為自己的下層")).toBeInTheDocument();
});

test("testEmployeeRoleSeesNoWriteButtons", async () => {
  open(["org.read"]);
  await userEvent.setup().click((await screen.findAllByText("工程部"))[0]);
  expect(await screen.findByText("上層部門", { selector: "dt" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "新增部門" })).toBeNull();
  expect(screen.queryByRole("button", { name: "編輯" })).toBeNull();
});
