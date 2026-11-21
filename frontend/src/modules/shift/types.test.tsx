import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ShiftType } from "../../api/types";
import type { MockRoutes } from "../../test/mockApi";
import { renderApp, testUser } from "../../test/renderApp";
import { shiftRegistration } from "./index";

const standard: ShiftType = { id: 1, code: "standard", name: "標準班", startTime: "09:00", endTime: "18:00", breakStart: "12:00", breakEnd: "13:00", isDefault: true, isActive: true };
const night: ShiftType = { id: 3, code: "night", name: "大夜班", startTime: "22:00", endTime: "06:00", breakStart: "02:00", breakEnd: "03:00", isDefault: false, isActive: true };

const open = (types: ShiftType[] = [standard, night], routes: MockRoutes = {}) =>
  renderApp({
    route: "/shifts/types", user: { ...testUser, role: "hr" }, permissions: ["shift.read", "shift.manage"], registrations: [shiftRegistration],
    routes: { "GET /api/shift/types": () => ({ body: types }), ...routes },
  });

const drawer = () => within(screen.getByRole("complementary", { name: "詳情" }));

test("testListShowsTimesAndCrossMidnight", async () => {
  const { api } = open();
  expect(await screen.findByText("22:00–06:00（跨日）")).toBeInTheDocument();
  expect(screen.getByText("09:00–18:00")).toBeInTheDocument();
  expect(api.calls.find((call) => call.path === "/api/shift/types")!.params.get("includeInactive")).toBe("true");
});

test("testCreateSendsTimesAndBreak", async () => {
  const { api } = open([standard], { "POST /api/shift/types": () => ({ status: 201, body: { ...night, id: 9 } }) });
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "新增班別" }));
  await user.type(drawer().getByLabelText("代碼"), "evening");
  await user.type(drawer().getByLabelText("名稱"), "晚班");
  await user.selectOptions(drawer().getByLabelText("上班"), "14:00");
  await user.selectOptions(drawer().getByLabelText("下班"), "23:00");
  await user.selectOptions(drawer().getByLabelText("休息開始"), "18:00");
  await user.selectOptions(drawer().getByLabelText("休息結束"), "19:00");
  await user.click(drawer().getByRole("button", { name: "儲存" }));
  await waitFor(() => expect(api.calls.find((call) => call.method === "POST")?.body).toEqual({
    code: "evening", name: "晚班", startTime: "14:00", endTime: "23:00", breakStart: "18:00", breakEnd: "19:00",
  }));
});

test("testSetDefaultAndDeactivate", async () => {
  const { api } = open([standard, night], { "PATCH /api/shift/types/3": ({ body }) => ({ body: { ...night, ...(body as object) } }) });
  const user = userEvent.setup();
  await user.click(await screen.findByText("大夜班"));
  await user.click(await drawer().findByRole("button", { name: "設為預設" }));
  await waitFor(() => expect(api.calls.some((call) => call.method === "PATCH" && (call.body as { isDefault?: boolean }).isDefault === true)).toBe(true));
});

test("testDefaultTypeCannotBeDeactivated", async () => {
  open();
  const user = userEvent.setup();
  await user.click(await screen.findByText("標準班"));
  expect(await drawer().findByRole("button", { name: "停用" })).toBeDisabled();
});

test("testWarnsWhenNoDefault", async () => {
  open([{ ...standard, isDefault: false }]);
  expect(await screen.findByText("目前沒有預設班：沒排班的人會被當作休息")).toBeInTheDocument();
});

test("testEditOnlySendsName", async () => {
  const { api } = open([standard, night], { "PATCH /api/shift/types/3": () => ({ body: { ...night, name: "夜班" } }) });
  const user = userEvent.setup();
  await user.click(await screen.findByText("大夜班"));
  await user.click(await drawer().findByRole("button", { name: "編輯" }));
  const name = drawer().getByLabelText("名稱");
  await user.clear(name);
  await user.type(name, "夜班");
  expect(drawer().queryByLabelText("上班")).not.toBeInTheDocument();
  await user.click(drawer().getByRole("button", { name: "儲存" }));
  await waitFor(() => expect(api.calls.find((call) => call.method === "PATCH")?.body).toEqual({ name: "夜班" }));
});
