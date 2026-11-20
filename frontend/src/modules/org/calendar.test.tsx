import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { CalendarDay } from "../../api/types";
import type { MockRoutes } from "../../test/mockApi";
import { renderApp } from "../../test/renderApp";
import { orgRegistration } from "./index";

const holiday: CalendarDay = { day: "2026-10-10", kind: "holiday", name: "國慶日" };
const makeup: CalendarDay = { day: "2026-02-07", kind: "makeup_workday", name: "春節補班" };

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(2026, 10, 20, 9, 30));
});
afterEach(() => vi.useRealTimers());

const open = (permissions: string[], routes: MockRoutes = {}) =>
  renderApp({
    route: "/calendar", permissions, registrations: [orgRegistration],
    routes: { "GET /api/org/calendarDays": () => ({ body: [makeup, holiday] }), ...routes },
  });

test("testListsDaysOfSelectedYear", async () => {
  const { api } = open(["org.read"]);
  expect(await screen.findByText("國慶日")).toBeInTheDocument();
  expect(screen.getByText("放假")).toBeInTheDocument();
  expect(screen.getByText("補班")).toBeInTheDocument();
  const first = api.calls.find((call) => call.path === "/api/org/calendarDays")!;
  expect(first.params.get("from")).toBe("2026-01-01");
  expect(first.params.get("to")).toBe("2026-12-31");
  await userEvent.setup({ advanceTimers: () => {} }).click(screen.getByRole("button", { name: "下一年" }));
  await waitFor(() => expect(api.calls.some((call) => call.params.get("from") === "2027-01-01")).toBe(true));
  expect(api.calls.find((call) => call.params.get("from") === "2027-01-01")?.params.get("to")).toBe("2027-12-31");
});

test("testCreateDayUsesPut", async () => {
  const { api } = open(["org.read", "org.manage"], {
    "PUT /api/org/calendarDays/2026-12-25": () => ({ body: { day: "2026-12-25", kind: "holiday", name: "行憲紀念日" } }),
  });
  const user = userEvent.setup({ advanceTimers: () => {} });
  await user.click(await screen.findByRole("button", { name: "新增日期" }));
  await user.type(screen.getByLabelText("日期"), "2026-12-25");
  await user.type(screen.getByLabelText("名稱"), "行憲紀念日");
  await user.click(screen.getByRole("button", { name: "儲存" }));
  await waitFor(() => expect(api.calls.find((call) => call.method === "PUT")?.body).toEqual({ kind: "holiday", name: "行憲紀念日" }));
});

test("testDeleteNeedsSecondClick", async () => {
  let deleted = false;
  const { api } = open(["org.read", "org.manage"], {
    "GET /api/org/calendarDays": () => ({ body: deleted ? [makeup] : [makeup, holiday] }),
    "DELETE /api/org/calendarDays/2026-10-10": () => { deleted = true; return { status: 204 }; },
  });
  const user = userEvent.setup({ advanceTimers: () => {} });
  await user.click(await screen.findByText("國慶日"));
  await user.click(await screen.findByRole("button", { name: "刪除" }));
  expect(api.calls.some((call) => call.method === "DELETE")).toBe(false);
  await user.click(screen.getByRole("button", { name: "確定刪除？" }));
  await waitFor(() => expect(api.calls.some((call) => call.method === "DELETE")).toBe(true));
  await waitFor(() => expect(screen.queryByText("國慶日")).toBeNull());
});

test("testEmployeeSeesNoWriteButtons", async () => {
  open(["org.read"]);
  await userEvent.setup({ advanceTimers: () => {} }).click(await screen.findByText("國慶日"));
  expect(await screen.findByText("種類", { selector: "dt" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "新增日期" })).toBeNull();
  expect(screen.queryByRole("button", { name: "編輯" })).toBeNull();
  expect(screen.queryByRole("button", { name: "刪除" })).toBeNull();
});
