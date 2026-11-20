import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { BrowserRouter, Route, Routes } from "react-router";
import { AuthProvider } from "./auth/AuthProvider";
import { LoginPage } from "./auth/LoginPage";
import { RequireAuth } from "./auth/RequireAuth";
import { usePermissions } from "./auth/usePermissions";
import { allRegistrations } from "./modules";
import type { ModuleRegistration } from "./modules/registry";
import { Shell } from "./shell/Shell";

// 路由本身不依權限過濾：沒權限的人直接輸入網址，要看到明確的說明，不是空白或 404
function PermissionGate({ requires, children }: { requires: string; children: ReactNode }) {
  const { can } = usePermissions();
  return can(requires) ? <>{children}</> : <div className="empty">沒有權限看這個頁面</div>;
}

function HomePlaceholder() {
  return <div className="empty">首頁</div>;
}

export function AppRoutes({ registrations = allRegistrations }: { registrations?: ModuleRegistration[] }) {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth><Shell registrations={registrations} /></RequireAuth>}>
        <Route index element={<HomePlaceholder />} />
        {registrations.flatMap((registration) => registration.pages).map((page) => (
          <Route key={page.key} path={page.path} element={<PermissionGate requires={page.requires}>{page.element}</PermissionGate>} />
        ))}
        <Route path="*" element={<div className="empty">找不到這個頁面</div>} />
      </Route>
    </Routes>
  );
}

export const createQueryClient = () => new QueryClient({ defaultOptions: { queries: { retry: false } } });

const queryClient = createQueryClient();

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <AppRoutes />
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
