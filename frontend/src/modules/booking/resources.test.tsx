import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Resource } from "../../api/types";
import type { MockRoutes } from "../../test/mockApi";
import { renderApp } from "../../test/renderApp";
import { bookingRegistration } from "./index";

const room: Resource = { id: 1, name: "3F 大會議室", kind: "room", location: "3 樓", capacity: 12, features: ["video"], isActive: true, note: null };
const projector: Resource = { id: 2, name: "可攜式投影機", kind: "equipment", location: null, capacity: null, features: [], isActive: true, note: null };
const manage = ["booking.read", "booking.resources.manage"];

const open = (permissions: string[], routes: MockRoutes = {}) =>
  renderApp({
    route: "/resources", permissions, registrations: [bookingRegistration],
    routes: { "GET /api/booking/resources": () => ({ body: [room, projector] }), ...routes },
  });

test("testListShowsResourcesWithKindLabels", async () => {
  open(["booking.read"]);
  expect(await screen.findByText("3F 大會議室")).toBeInTheDocument();
  expect(screen.getByText("可攜式投影機")).toBeInTheDocument();
  expect(screen.getByText("會議室")).toBeInTheDocument();
  expect(screen.getByText("設備")).toBeInTheDocument();
});

test("testEmployeeSeesNoWriteButtons", async () => {
  open(["booking.read"]);
  const user = userEvent.setup();
  await user.click(await screen.findByText("3F 大會議室"));
  expect(await screen.findByText("設備特色")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "新增資源" })).toBeNull();
  expect(screen.queryByRole("button", { name: "編輯" })).toBeNull();
  expect(screen.queryByRole("button", { name: "停用" })).toBeNull();
});

test("testAdminCreatesResource", async () => {
  const { api } = open(manage, { "POST /api/booking/resources": () => ({ status: 201, body: { ...room, id: 3 } }) });
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "新增資源" }));
  await user.type(screen.getByLabelText("名稱"), "新會議室");
  await user.type(screen.getByLabelText(/特色/), "video, whiteboard");
  await user.click(screen.getByRole("button", { name: "儲存" }));
  await waitFor(() => expect(api.calls.some((call) => call.method === "POST")).toBe(true));
  expect(api.calls.find((call) => call.method === "POST")?.body).toEqual({
    name: "新會議室", kind: "room", location: null, capacity: null, features: ["video", "whiteboard"], note: null,
  });
  await waitFor(() => expect(api.calls.filter((call) => call.method === "GET" && call.path === "/api/booking/resources").length).toBeGreaterThan(1));
});

test("testEditSendsOnlyChangedFields", async () => {
  const { api } = open(manage, { "PATCH /api/booking/resources/1": () => ({ body: room }) });
  const user = userEvent.setup();
  await user.click(await screen.findByText("3F 大會議室"));
  await user.click(await screen.findByRole("button", { name: "編輯" }));
  const location = screen.getByLabelText("地點");
  await user.clear(location);
  await user.type(location, "4 樓");
  await user.click(screen.getByRole("button", { name: "儲存" }));
  await waitFor(() => expect(api.calls.some((call) => call.method === "PATCH")).toBe(true));
  expect(api.calls.find((call) => call.method === "PATCH")?.body).toEqual({ location: "4 樓" });
});

test("testDeactivateRefreshesAndShowsInactiveTag", async () => {
  let inactive = false;
  const { api } = open(manage, {
    "GET /api/booking/resources": ({ params }) => ({
      body: inactive ? (params.get("includeInactive") ? [{ ...room, isActive: false }, projector] : [projector]) : [room, projector],
    }),
    "PATCH /api/booking/resources/1": () => { inactive = true; return { body: { ...room, isActive: false } }; },
  });
  const user = userEvent.setup();
  await user.click(await screen.findByText("3F 大會議室"));
  await user.click(await screen.findByRole("button", { name: "停用" }));
  await waitFor(() => expect(api.calls.find((call) => call.method === "PATCH")?.body).toEqual({ isActive: false }));
  await waitFor(() => expect(screen.queryByText("3F 大會議室")).toBeNull());
  await user.click(screen.getByLabelText("含已停用"));
  expect(await screen.findByText("已停用")).toBeInTheDocument();
});

test("testDuplicateNameShowsServerMessage", async () => {
  open(manage, { "POST /api/booking/resources": () => ({ status: 409, body: { error: { code: "DUPLICATE", message: "資源名稱已存在", details: null } } }) });
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "新增資源" }));
  await user.type(screen.getByLabelText("名稱"), "3F 大會議室");
  await user.click(screen.getByRole("button", { name: "儲存" }));
  expect(await screen.findByText("資源名稱已存在")).toBeInTheDocument();
  expect(screen.getByLabelText("名稱")).toBeInTheDocument();
});
