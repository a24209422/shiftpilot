import { visiblePages, type PageRegistration } from "./registry";

const page = (key: string, requires: string, order: number): PageRegistration => (
  { key, path: `/${key}`, name: key, en: key, icon: "events", requires, element: null, order }
);

test("testVisiblePagesFiltersByPermissionAndSortsByOrder", () => {
  const registrations = [
    { backendModule: "booking", pages: [page("booking", "booking.read", 3)] },
    { backendModule: "core", pages: [page("users", "core.users.manage", 1)] },
    { backendModule: "org", pages: [page("org", "org.read", 2)] },
  ];
  const granted = new Set(["booking.read", "org.read"]);
  expect(visiblePages(registrations, (permission) => granted.has(permission)).map((item) => item.key)).toEqual(["org", "booking"]);
});
