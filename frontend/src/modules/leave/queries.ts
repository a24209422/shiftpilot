import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../../api/client";
import type { LeaveAdjustment, LeaveBalance, LeaveRequest, LeaveType, UnusedLeave } from "../../api/types";

// queryKey 都放在 ["leave", …] 底下：任何寫入只要 invalidate ["leave"]，餘額、列表、首頁方塊、時間軸會一起更新
export const useLeaveTypes = (includeInactive = false) =>
  useQuery({
    queryKey: ["leave", "types", { includeInactive }],
    queryFn: () => apiGet<LeaveType[]>("/api/leave/types", { includeInactive: includeInactive || undefined }),
  });

export const useLeaveBalances = (employeeId: number | null = null, enabled = true) =>
  useQuery({
    queryKey: ["leave", "balances", employeeId ?? "me"],
    queryFn: () => apiGet<LeaveBalance[]>("/api/leave/balances", { employeeId: employeeId ?? undefined }),
    enabled,
  });

export const useLeaveRequests = (scope: "mine" | "toApprove" | "all", enabled = true) =>
  useQuery({
    queryKey: ["leave", "requests", scope],
    queryFn: () => apiGet<LeaveRequest[]>("/api/leave/requests", { scope }),
    enabled,
  });

export const useLeaveRequest = (id: string | null) =>
  useQuery({
    queryKey: ["leave", "request", id],
    queryFn: () => apiGet<LeaveRequest>(`/api/leave/requests/${id}`),
    enabled: id !== null,
  });

export const useAdjustments = (employeeId: number | null) =>
  useQuery({
    queryKey: ["leave", "adjustments", employeeId],
    queryFn: () => apiGet<LeaveAdjustment[]>("/api/leave/adjustments", { employeeId: employeeId ?? undefined }),
    enabled: employeeId !== null,
  });

export const useUnused = (from: string, to: string) =>
  useQuery({
    queryKey: ["leave", "unused", from, to],
    queryFn: () => apiGet<UnusedLeave[]>("/api/leave/unused", { periodEndFrom: from, periodEndTo: to }),
    enabled: Boolean(from && to),
  });
