import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { apiGet } from "../api/client";
import type { VisibleModule } from "../api/types";
import { useAuth } from "./AuthProvider";

const noModules: VisibleModule[] = [];

// 前端的「我有哪些權限」= 後端 /api/modules 每個模組列出的權限聯集。只用來決定顯示什麼，真正的檢查在後端
export function usePermissions() {
  const { status } = useAuth();
  const query = useQuery({ queryKey: ["modules"], queryFn: () => apiGet<VisibleModule[]>("/api/modules"), enabled: status === "signedIn" });
  const modules = query.data ?? noModules;
  const granted = useMemo(() => new Set(modules.flatMap((item) => item.permissions)), [modules]);
  return { can: (permission: string) => granted.has(permission), modules, isLoading: query.isLoading };
}
