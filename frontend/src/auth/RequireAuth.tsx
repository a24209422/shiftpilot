import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router";
import { useAuth } from "./AuthProvider";

export function RequireAuth({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const location = useLocation();
  if (status === "loading") return <div className="loginWrap">載入中…</div>;
  if (status === "signedOut") return <Navigate to="/login" replace state={{ from: `${location.pathname}${location.search}` }} />;
  return <>{children}</>;
}
