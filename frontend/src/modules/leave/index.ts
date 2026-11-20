import { createElement } from "react";
import type { ModuleRegistration } from "../registry";
import { LeaveAdminPage } from "./LeaveAdminPage";
import { LeavePage } from "./LeavePage";

export const leaveRegistration: ModuleRegistration = {
  backendModule: "leave",
  pages: [
    { key: "leave", path: "/leave", name: "請假", en: "Time off", icon: "leave", requires: "leave.request", element: createElement(LeavePage), order: 25 },
    { key: "leaveAdmin", path: "/leave/admin", name: "假別與額度", en: "Leave rules", icon: "leave", requires: "leave.manage", element: createElement(LeaveAdminPage), order: 26 },
  ],
};
