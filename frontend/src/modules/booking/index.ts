import { createElement } from "react";
import type { ModuleRegistration } from "../registry";
import { ResourcesPage } from "./ResourcesPage";

export const bookingRegistration: ModuleRegistration = {
  backendModule: "booking",
  pages: [
    { key: "resources", path: "/resources", name: "資源", en: "Resources", icon: "resources", requires: "booking.read", element: createElement(ResourcesPage), order: 20 },
  ],
};
