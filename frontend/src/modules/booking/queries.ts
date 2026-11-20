import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../../api/client";
import type { Booking, Resource } from "../../api/types";
import { addDays, toLocalString } from "../../forms/time";

export const useResources = (includeInactive = false) =>
  useQuery({
    queryKey: ["resources", { includeInactive }],
    queryFn: () => apiGet<Resource[]>("/api/booking/resources", { includeInactive: includeInactive || undefined }),
  });

// 後端回傳「與這段時間重疊」的排程，所以跨週的排程兩週都會出現
export const useBookings = (weekStartDate: Date, includeCancelled: boolean) => {
  const from = toLocalString(weekStartDate);
  const to = toLocalString(addDays(weekStartDate, 7));
  return useQuery({
    queryKey: ["bookings", from, includeCancelled],
    queryFn: () => apiGet<Booking[]>("/api/booking/bookings", { from, to, includeCancelled: includeCancelled || undefined }),
  });
};
