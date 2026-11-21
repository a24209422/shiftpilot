import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../../api/client";
import type { ScheduleDay, ShiftRoster, ShiftType } from "../../api/types";

// queryKey 都放在 ["shifts", …] 底下：任何排班的寫入只要 invalidate ["shifts"]，班表頁與時間軸會一起更新
export const useShiftTypes = (includeInactive = false) =>
  useQuery({
    queryKey: ["shifts", "types", { includeInactive }],
    queryFn: () => apiGet<ShiftType[]>("/api/shift/types", { includeInactive: includeInactive || undefined }),
  });

export const useSchedule = (from: string, to: string) =>
  useQuery({
    queryKey: ["shifts", "schedule", from, to],
    queryFn: () => apiGet<ScheduleDay[]>("/api/shift/schedule", { from, to }),
  });

export const useRosters = (employeeId: number | null) =>
  useQuery({
    queryKey: ["shifts", "rosters", employeeId],
    queryFn: () => apiGet<ShiftRoster[]>("/api/shift/rosters", { employeeId: employeeId ?? undefined }),
    enabled: employeeId !== null,
  });
