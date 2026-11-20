import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { apiGet } from "../../api/client";
import type { AuditEntry, User } from "../../api/types";

export const auditPageSize = 100;

export const useUsers = (enabled = true) =>
  useQuery({ queryKey: ["users"], queryFn: () => apiGet<User[]>("/api/core/users"), enabled });

// 稽核紀錄由新到舊；下一頁用這一頁最後一筆的 id 當 beforeId
export const useAudit = (module: string) =>
  useInfiniteQuery({
    queryKey: ["audit", module],
    initialPageParam: undefined as number | undefined,
    queryFn: ({ pageParam }) =>
      apiGet<AuditEntry[]>("/api/core/audit", { module: module || undefined, limit: auditPageSize, beforeId: pageParam }),
    getNextPageParam: (last) => (last.length < auditPageSize ? undefined : last[last.length - 1].id),
  });
