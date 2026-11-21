import { createElement } from "react";
import type { ModuleRegistration } from "../registry";
import { ShiftsPage } from "./ShiftsPage";
import { ShiftTypesPage } from "./ShiftTypesPage";
import { shiftTimelineSource } from "./timeline";

export const shiftRegistration: ModuleRegistration = {
  backendModule: "shift",
  pages: [
    { key: "shifts", path: "/shifts", name: "班表", en: "Shifts", icon: "shift", requires: "shift.read", element: createElement(ShiftsPage), order: 27 },
    { key: "shiftTypes", path: "/shifts/types", name: "班別", en: "Shift types", icon: "shift", requires: "shift.manage", element: createElement(ShiftTypesPage), order: 28 },
  ],
  timelineSources: [shiftTimelineSource],
};
