import { createElement } from "react";
import type { ModuleRegistration } from "../registry";
import { BookingsPage } from "./BookingsPage";
import { ResourcesPage } from "./ResourcesPage";

export const bookingRegistration: ModuleRegistration = {
  backendModule: "booking",
  pages: [
    { key: "bookings", path: "/bookings", name: "排程", en: "Events", icon: "events", requires: "booking.read", element: createElement(BookingsPage), order: 10 },
    { key: "resources", path: "/resources", name: "資源", en: "Resources", icon: "resources", requires: "booking.read", element: createElement(ResourcesPage), order: 20 },
  ],
};
