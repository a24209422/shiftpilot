import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { allRegistrations } from "./modules";
import { renderApp, testUser } from "./test/renderApp";

// 設計補充的「寫入動作核對表」自動版：管理員逐頁操作，每個寫入動作都要找得到按鈕

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(2026, 10, 20, 9, 30));
});
afterEach(() => vi.useRealTimers());

const allPermissions = [
  "org.read", "org.manage", "booking.read", "booking.write", "booking.writeAny", "booking.resources.manage", "core.users.manage", "core.audit.read",
];
const employee = { id: 2, employeeNo: "E002", name: "林小美", email: null, departmentId: 1, jobTitle: "工程師", managerId: null, hiredOn: "2024-01-01", isActive: true, leftOn: null };
const booking = {
  id: 7, title: "團隊週會", category: "會議", startAt: "2026-11-17T10:00:00", endAt: "2026-11-17T11:00:00", status: "confirmed", note: null,
  createdBy: testUser.id, createdAt: "2026-11-16T08:00:00", resources: [{ id: 1, name: "3F 大會議室", kind: "room" }],
  participants: [{ employeeId: 2, name: "林小美", role: "organizer" }],
};
const routes = {
  "GET /api/org/departments": () => ({ body: [{ id: 1, name: "工程部", parentId: null }] }),
  "GET /api/org/employees": () => ({ body: [employee] }),
  "GET /api/org/calendarDays": () => ({ body: [{ day: "2026-10-10", kind: "holiday", name: "國慶日" }] }),
  "GET /api/booking/resources": () => ({ body: [{ id: 1, name: "3F 大會議室", kind: "room", location: null, capacity: 12, features: [], isActive: true, note: null }] }),
  "GET /api/booking/bookings": () => ({ body: [booking] }),
  "GET /api/core/users": () => ({ body: [{ id: 2, email: "lin@example.com", role: "manager", employeeId: 2, employeeName: "林小美", isActive: true, lastLoginAt: null, lockedUntil: null, createdAt: "2026-11-01T08:00:00" }] }),
};

// 每一頁：頁面層級的按鈕、點哪一列、那一列的詳情裡該有的按鈕
const pages = [
  { path: "/users", row: "lin@example.com", pageButtons: ["新增帳號"], rowButtons: ["編輯", "重設密碼"] },
  { path: "/departments", row: "工程部", pageButtons: ["新增部門"], rowButtons: ["編輯"] },
  { path: "/employees", row: "林小美", pageButtons: ["新增員工"], rowButtons: ["編輯", "停用"] },
  { path: "/calendar", row: "國慶日", pageButtons: ["新增日期"], rowButtons: ["編輯", "刪除"] },
  { path: "/resources", row: "3F 大會議室", pageButtons: ["新增資源"], rowButtons: ["編輯", "停用"] },
  { path: "/bookings", row: "團隊週會", pageButtons: ["新增排程"], rowButtons: ["編輯", "取消排程"] },
];

const has = (name: string) => screen.findByRole("button", { name }, { timeout: 1500 }).then(() => true, () => false);

test("testEveryWriteActionHasAnEntry", async () => {
  const missing: string[] = [];
  for (const page of pages) {
    const view = renderApp({ route: page.path, permissions: allPermissions, routes, registrations: allRegistrations });
    for (const name of page.pageButtons) if (!(await has(name))) missing.push(`${page.path}：${name}`);
    for (const name of ["改密碼", "登出"]) if (!(await has(name))) missing.push(`${page.path}：${name}`);
    await userEvent.setup().click((await screen.findAllByText(page.row))[0]);
    for (const name of page.rowButtons) if (!(await has(name))) missing.push(`${page.path} 的詳情：${name}`);
    view.unmount();
  }
  expect(missing).toEqual([]);
}, 60000);
