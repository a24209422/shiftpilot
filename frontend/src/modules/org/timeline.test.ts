import type { Department, Employee } from "../../api/types";
import { toEmployeeSubjects } from "./timeline";

const employee = (id: number, name: string, departmentId: number, isActive = true): Employee => ({
  id, employeeNo: `E${id}`, name, email: null, departmentId, jobTitle: "工程師", managerId: null, hiredOn: "2025-01-01", isActive, leftOn: null,
});
const departments: Department[] = [{ id: 1, name: "業務部", parentId: null }, { id: 2, name: "工程部", parentId: null }];

test("testEmployeesGroupedByDepartmentAndInactiveHidden", () => {
  const subjects = toEmployeeSubjects([employee(1, "王小明", 1), employee(2, "林小美", 2), employee(3, "陳離職", 2, false)], departments);
  expect(subjects).toEqual([
    { id: 2, label: "林小美", group: "工程部" },
    { id: 1, label: "王小明", group: "業務部" },
  ]);
});
