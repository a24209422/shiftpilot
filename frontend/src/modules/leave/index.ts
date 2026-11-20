import { createElement } from "react";
import type { ModuleRegistration } from "../registry";
import { LeavePage } from "./LeavePage";

export const leaveRegistration: ModuleRegistration = {
  backendModule: "leave",
  pages: [
    { key: "leave", path: "/leave", name: "請假", en: "Time off", icon: "leave", requires: "leave.request", element: createElement(LeavePage), order: 25 },
  ],
};
