import { createElement } from "react";
import type { ModuleRegistration } from "../registry";
import { ShiftTypesPage } from "./ShiftTypesPage";

export const shiftRegistration: ModuleRegistration = {
  backendModule: "shift",
  pages: [
    { key: "shiftTypes", path: "/shifts/types", name: "班別", en: "Shift types", icon: "shift", requires: "shift.manage", element: createElement(ShiftTypesPage), order: 28 },
  ],
};
