import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../../api/client";
import type { Department, Employee } from "../../api/types";

export const useDepartments = () =>
  useQuery({ queryKey: ["departments"], queryFn: () => apiGet<Department[]>("/api/org/departments") });

export const useEmployees = (includeInactive = false) =>
  useQuery({
    queryKey: ["employees", { includeInactive }],
    queryFn: () => apiGet<Employee[]>("/api/org/employees", { includeInactive: includeInactive || undefined }),
  });
