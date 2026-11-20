import { apiGet } from "../../api/client";
import type { Department, Employee } from "../../api/types";
import type { TimelineSubject, TimelineView } from "../../timeline/types";

// 時間軸依出現順序分組，所以先依部門再依姓名排好
export function toEmployeeSubjects(employees: Employee[], departments: Department[]): TimelineSubject[] {
  const departmentNames = new Map(departments.map((item) => [item.id, item.name]));
  return employees
    .filter((employee) => employee.isActive)
    .map((employee) => ({ id: employee.id, label: employee.name, group: departmentNames.get(employee.departmentId) ?? "未分部門" }))
    .sort((a, b) => a.group.localeCompare(b.group, "zh-Hant") || a.label.localeCompare(b.label, "zh-Hant"));
}

export const employeeTimelineView: TimelineView = {
  key: "employees",
  name: "員工",
  subjectType: "employee",
  requires: "org.read",
  emptyText: "還沒有員工",
  // 不能跟 useEmployees 共用 queryKey：那邊快取的是 Employee[]，這裡是轉換後的列
  subjects: () => ({
    queryKey: ["employees", "timeline"],
    queryFn: async () => {
      const [employees, departments] = await Promise.all([
        apiGet<Employee[]>("/api/org/employees"),
        apiGet<Department[]>("/api/org/departments"),
      ]);
      return toEmployeeSubjects(employees, departments);
    },
  }),
};
