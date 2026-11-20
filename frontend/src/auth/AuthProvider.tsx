import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { apiGet, apiSend, onSessionExpired } from "../api/client";
import type { CurrentUser } from "../api/types";

type Status = "loading" | "signedIn" | "signedOut";
interface AuthValue {
  user: CurrentUser | null;
  status: Status;
  notice: string | null;
  login(email: string, password: string): Promise<void>;
  logout(): Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [status, setStatus] = useState<Status>("loading");
  const [notice, setNotice] = useState<string | null>(null);
  // 啟動時查 /me 的 401 是「還沒登入」，不是「過期」；只有登入中收到 401 才顯示過期訊息
  const statusRef = useRef<Status>("loading");
  const update = useCallback((next: Status, nextUser: CurrentUser | null) => {
    statusRef.current = next;
    setStatus(next);
    setUser(nextUser);
  }, []);

  useEffect(() => {
    let cancelled = false;
    apiGet<{ user: CurrentUser }>("/api/auth/me")
      .then((result) => { if (!cancelled) update("signedIn", result.user); })
      .catch(() => { if (!cancelled) update("signedOut", null); });
    return () => { cancelled = true; };
  }, [update]);

  useEffect(() => onSessionExpired(() => {
    if (statusRef.current !== "signedIn") return;
    queryClient.clear();
    setNotice("登入已過期，請重新登入");
    update("signedOut", null);
  }), [queryClient, update]);

  const login = useCallback(async (email: string, password: string) => {
    const result = await apiSend<{ user: CurrentUser }>("POST", "/api/auth/login", { email, password });
    queryClient.clear();
    setNotice(null);
    update("signedIn", result.user);
  }, [queryClient, update]);

  const logout = useCallback(async () => {
    try {
      await apiSend("POST", "/api/auth/logout");
    } finally {
      // 就算請求失敗，畫面也要回到登入頁，不能讓人以為還登入著
      queryClient.clear();
      setNotice(null);
      update("signedOut", null);
    }
  }, [queryClient, update]);

  const value = useMemo(() => ({ user, status, notice, login, logout }), [user, status, notice, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth 要放在 AuthProvider 裡面");
  return value;
}
