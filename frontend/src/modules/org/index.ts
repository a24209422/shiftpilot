import { createElement } from "react";
import type { ModuleRegistration } from "../registry";
import { CalendarPage } from "./CalendarPage";
import { DepartmentsPage } from "./DepartmentsPage";
import { EmployeesPage } from "./EmployeesPage";

export const orgRegistration: ModuleRegistration = {
  backendModule: "org",
  pages: [
    { key: "employees", path: "/employees", name: "員工", en: "People", icon: "people", requires: "org.read", element: createElement(EmployeesPage), order: 30 },
    { key: "departments", path: "/departments", name: "部門", en: "Departments", icon: "building", requires: "org.read", element: createElement(DepartmentsPage), order: 40 },
    { key: "calendar", path: "/calendar", name: "行事曆", en: "Calendar", icon: "calendar", requires: "org.read", element: createElement(CalendarPage), order: 50, hideFromNav: true },
  ],
};
