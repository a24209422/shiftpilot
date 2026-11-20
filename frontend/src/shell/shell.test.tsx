import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ModuleRegistration } from "../modules/registry";
import { renderApp, testUser } from "../test/renderApp";
import { Drawer } from "./Drawer";
import { useDrawerParams } from "./useDrawerParams";

function DrawerProbe() {
  const { selectedId, close } = useDrawerParams();
  return (
    <>
      <div>{`選取：${selectedId}`}</div>
      <Drawer open={selectedId !== null} title="測試面板" onClose={close}><p>面板內容</p></Drawer>
    </>
  );
}

const registrations: ModuleRegistration[] = [
  {
    backendModule: "test",
    pages: [
      { key: "bookings", path: "/bookings", name: "排程頁", en: "Events", icon: "events", requires: "booking.read", element: <div>排程內容</div>, order: 1 },
      { key: "users", path: "/users", name: "帳號頁", en: "Accounts", icon: "key", requires: "core.users.manage", element: <div>帳號內容</div>, order: 2 },
      { key: "probe", path: "/probe", name: "面板頁", en: "Probe", icon: "log", requires: "booking.read", element: <DrawerProbe />, order: 3 },
    ],
  },
];
const manager = { ...testUser, role: "manager" as const, employeeName: "王小明" };

test("testSidebarShowsUserAndOnlyPermittedPages", async () => {
  renderApp({ user: manager, permissions: ["booking.read"], registrations });
  expect(await screen.findByRole("link", { name: /排程頁/ })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /帳號頁/ })).toBeNull();
  expect(screen.getByText("王小明・主管")).toBeInTheDocument();
});

test("testPageWithoutPermissionShowsExplanation", async () => {
  renderApp({ route: "/users", permissions: ["booking.read"], registrations });
  expect(await screen.findByText("沒有權限看這個頁面")).toBeInTheDocument();
  expect(screen.queryByText("帳號內容")).toBeNull();
});

test("testChangePasswordMismatchIsBlockedLocally", async () => {
  const { api } = renderApp({ permissions: ["booking.read"], registrations });
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "改密碼" }));
  await user.type(screen.getByLabelText("目前密碼"), "old-password");
  await user.type(screen.getByLabelText("新密碼"), "new-password-1");
  await user.type(screen.getByLabelText("再輸入一次新密碼"), "new-password-2");
  await user.click(screen.getByRole("button", { name: "更新密碼" }));
  expect(await screen.findByText("兩次輸入的新密碼不一樣")).toBeInTheDocument();
  expect(api.calls.some((call) => call.path === "/api/auth/password")).toBe(false);
});

test("testChangePasswordSuccessSignsOut", async () => {
  const { api } = renderApp({
    permissions: ["booking.read"], registrations,
    routes: { "POST /api/auth/password": () => ({ status: 204 }) },
  });
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "改密碼" }));
  await user.type(screen.getByLabelText("目前密碼"), "old-password");
  await user.type(screen.getByLabelText("新密碼"), "new-password-1");
  await user.type(screen.getByLabelText("再輸入一次新密碼"), "new-password-1");
  await user.click(screen.getByRole("button", { name: "更新密碼" }));
  expect(await screen.findByText("密碼已更新，請用新密碼登入")).toBeInTheDocument();
  expect(api.calls.find((call) => call.path === "/api/auth/password")?.body).toEqual({ currentPassword: "old-password", newPassword: "new-password-1" });
});

test("testDrawerStateLivesInUrl", async () => {
  renderApp({ route: "/probe?id=3", permissions: ["booking.read"], registrations });
  expect(await screen.findByText("選取：3")).toBeInTheDocument();
  expect(screen.getByText("面板內容")).toBeInTheDocument();
  await userEvent.setup().click(screen.getByRole("button", { name: "關閉" }));
  await waitFor(() => expect(screen.getByTestId("location").textContent).toBe("/probe"));
});

test("testLogoutReturnsToLogin", async () => {
  const { api } = renderApp({ permissions: ["booking.read"], registrations, routes: { "POST /api/auth/logout": () => ({ status: 204 }) } });
  await userEvent.setup().click(await screen.findByRole("button", { name: "登出" }));
  expect(await screen.findByRole("button", { name: "登入" })).toBeInTheDocument();
  expect(api.calls.some((call) => call.path === "/api/auth/logout")).toBe(true);
  expect(screen.queryByText("登入已過期，請重新登入")).toBeNull();
});

test("testSidebarDateStampIsYearMonthDay", async () => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(2026, 10, 21, 9, 0));
  try {
    renderApp({ permissions: ["booking.read"], registrations });
    expect(await screen.findByText("2026.11.21 SAT")).toBeInTheDocument();
  } finally {
    vi.useRealTimers();
  }
});
