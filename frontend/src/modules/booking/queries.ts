import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../../api/client";
import type { Resource } from "../../api/types";

export const useResources = (includeInactive = false) =>
  useQuery({
    queryKey: ["resources", { includeInactive }],
    queryFn: () => apiGet<Resource[]>("/api/booking/resources", { includeInactive: includeInactive || undefined }),
  });
