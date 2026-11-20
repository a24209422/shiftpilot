import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router";
import { AuthProvider } from "./auth/AuthProvider";
import { LoginPage } from "./auth/LoginPage";
import { RequireAuth } from "./auth/RequireAuth";
import { usePermissions } from "./auth/usePermissions";

// 暫時的外殼佔位：Task 5 換成真正的外殼
function ShellPlaceholder() {
  usePermissions();
  return (
    <div className="app">
      <nav className="sidebar" />
      <main className="main" />
      <aside className="sidePanelSlot" />
    </div>
  );
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="*" element={<RequireAuth><ShellPlaceholder /></RequireAuth>} />
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
