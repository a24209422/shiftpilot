import { createElement } from "react";
import type { ModuleRegistration } from "../registry";
import { AuditPage } from "./AuditPage";
import { UsersPage } from "./UsersPage";

export const coreRegistration: ModuleRegistration = {
  backendModule: "core",
  pages: [
    { key: "users", path: "/users", name: "帳號", en: "Accounts", icon: "key", requires: "core.users.manage", element: createElement(UsersPage), order: 60 },
    { key: "audit", path: "/audit", name: "稽核", en: "Audit log", icon: "log", requires: "core.audit.read", element: createElement(AuditPage), order: 70 },
  ],
};
