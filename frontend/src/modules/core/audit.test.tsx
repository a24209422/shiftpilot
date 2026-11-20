import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { AuditEntry } from "../../api/types";
import { renderApp } from "../../test/renderApp";
import { coreRegistration } from "./index";

const entry = (id: number, extra: Partial<AuditEntry> = {}): AuditEntry => ({
  id, at: "2026-11-20T08:00:00", userId: 1, module: "booking", action: "createBooking", entity: "booking", entityId: String(id), before: null, after: { title: `預約${id}` }, ...extra,
});
const firstPage = Array.from({ length: 100 }, (_, index) => entry(600 - index));
const secondPage = [entry(500), entry(499), entry(498)];

const open = (route = "/audit") =>
  renderApp({
    route, permissions: ["core.users.manage", "core.audit.read"], registrations: [coreRegistration],
    routes: {
      "GET /api/core/users": () => ({ body: [{ id: 1, email: "admin@example.com", role: "admin", employeeId: null, employeeName: null, isActive: true, lastLoginAt: null, lockedUntil: null, createdAt: "2026-11-01T08:00:00" }] }),
      "GET /api/core/audit": ({ params }) => ({ body: params.get("beforeId") ? secondPage : firstPage }),
    },
  });

test("testFirstPageThenLoadMoreUsesBeforeId", async () => {
  const { api } = open();
  const ui = userEvent.setup();
  await screen.findAllByText("admin@example.com");
  await ui.click(await screen.findByRole("button", { name: "載入更多" }));
  await waitFor(() => expect(api.calls.some((call) => call.params.get("beforeId") === "501")).toBe(true));
  await waitFor(() => expect(screen.queryByRole("button", { name: "載入更多" })).toBeNull());
  expect(api.calls[api.calls.findIndex((call) => call.path === "/api/core/audit")].params.get("limit")).toBe("100");
});

test("testModuleFilterSendsModule", async () => {
  const { api } = open();
  await screen.findAllByText("admin@example.com");
  await userEvent.setup().selectOptions(screen.getByLabelText("模組"), "org");
  await waitFor(() => expect(api.calls.some((call) => call.path === "/api/core/audit" && call.params.get("module") === "org")).toBe(true));
});

test("testDetailShowsBeforeAndAfter", async () => {
  open();
  await screen.findAllByText("admin@example.com");
  await userEvent.setup().click(screen.getAllByText("createBooking")[0]);
  expect(await screen.findByText(/"title": "預約600"/)).toBeInTheDocument();
});
