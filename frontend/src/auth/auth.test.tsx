import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createQueryClient } from "../App";
import { mockApi } from "../test/mockApi";
import { renderApp, testUser } from "../test/renderApp";
import { AuthProvider } from "./AuthProvider";
import { usePermissions } from "./usePermissions";

const unauthenticated = { status: 401, body: { error: { code: "UNAUTHENTICATED", message: "請先登入", details: null } } };

async function fillAndSubmit() {
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText("Email"), "a@example.com");
  await user.type(screen.getByLabelText("密碼"), "password123");
  await user.click(screen.getByRole("button", { name: "登入" }));
}

const location = () => screen.getByTestId("location").textContent;

test("testSignedOutUserSeesLoginPage", async () => {
  renderApp({ route: "/bookings", user: null });
  expect(await screen.findByRole("button", { name: "登入" })).toBeInTheDocument();
  expect(screen.queryByText("登入已過期，請重新登入")).toBeNull();
});

test("testLoginShowsShellAndReturnsToRequestedPage", async () => {
  const { api } = renderApp({
    route: "/bookings", user: null,
    routes: { "POST /api/auth/login": () => ({ body: { user: testUser } }) },
  });
  await fillAndSubmit();
  await waitFor(() => expect(document.querySelector(".app")).not.toBeNull());
  expect(api.calls.find((c) => c.path === "/api/auth/login")?.body).toEqual({ email: "a@example.com", password: "password123" });
  expect(location()).toBe("/bookings");
});

test("testWrongPasswordShowsMessage", async () => {
  renderApp({
    user: null,
    routes: { "POST /api/auth/login": () => ({ status: 401, body: { error: { code: "INVALID_CREDENTIALS", message: "x", details: null } } }) },
  });
  await fillAndSubmit();
  expect(await screen.findByText("帳號或密碼錯誤")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "登入" })).toBeInTheDocument();
});

test("testLockedAccountShowsServerMessage", async () => {
  renderApp({
    user: null,
    routes: { "POST /api/auth/login": () => ({ status: 429, body: { error: { code: "TOO_MANY_ATTEMPTS", message: "嘗試太多次，請 15 分鐘後再試", details: null } } }) },
  });
  await fillAndSubmit();
  expect(await screen.findByText("嘗試太多次，請 15 分鐘後再試")).toBeInTheDocument();
});

test("testSessionExpiryReturnsToLoginWithNotice", async () => {
  // /me 成功、之後 /modules 回 401：模擬用到一半 session 失效
  renderApp({ route: "/bookings", routes: { "GET /api/modules": () => unauthenticated } });
  expect(await screen.findByText("登入已過期，請重新登入")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "登入" })).toBeInTheDocument();
  expect(location()).toBe("/login");
});

test.todo("testLogoutReturnsToLogin");

function PermissionProbe() {
  const { can } = usePermissions();
  return <div>{`${can("booking.write")}|${can("core.users.manage")}`}</div>;
}

test("testPermissionsComeFromModules", async () => {
  mockApi({
    "GET /api/auth/me": () => ({ body: { user: testUser } }),
    "GET /api/modules": () => ({ body: [{ name: "booking", title: "資源預約", permissions: ["booking.read", "booking.write"] }] }),
  });
  render(<QueryClientProvider client={createQueryClient()}><AuthProvider><PermissionProbe /></AuthProvider></QueryClientProvider>);
  expect(await screen.findByText("true|false")).toBeInTheDocument();
});
