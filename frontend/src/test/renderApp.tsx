import { QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { AppRoutes, createQueryClient } from "../App";
import type { CurrentUser } from "../api/types";
import { AuthProvider } from "../auth/AuthProvider";
import type { ModuleRegistration } from "../modules/registry";
import { mockApi, type MockRoutes } from "./mockApi";

export const testUser: CurrentUser = { id: 1, email: "admin@example.com", role: "admin", employeeId: null, employeeName: null };

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}{location.search}</div>;
}

interface Options { route?: string; user?: CurrentUser | null; permissions?: string[]; routes?: MockRoutes; registrations?: ModuleRegistration[] }

// 自動登記 /me 與 /modules；user 為 null 代表尚未登入
export function renderApp({ route = "/", user = testUser, permissions = [], routes = {}, registrations }: Options = {}) {
  const unauthenticated = { status: 401, body: { error: { code: "UNAUTHENTICATED", message: "請先登入", details: null } } };
  const api = mockApi({
    "GET /api/auth/me": () => (user ? { body: { user } } : unauthenticated),
    "GET /api/modules": () => (user ? { body: [{ name: "test", title: "測試", permissions }] } : unauthenticated),
    ...routes,
  });
  const queryClient = createQueryClient();
  const view = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>
        <AuthProvider>
          <AppRoutes registrations={registrations} />
          <LocationProbe />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...view, api, queryClient };
}
