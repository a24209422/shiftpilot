import type { ReactNode } from "react";
import type { IconName } from "../shell/icons";

export interface PageRegistration {
  key: string;
  path: string;
  name: string;
  en: string;
  icon: IconName;
  // 需要的權限；沒有這個權限就不出現在導覽與首頁方塊
  requires: string;
  element: ReactNode;
  order: number;
}

export interface ModuleRegistration {
  backendModule: string;
  pages: PageRegistration[];
}

export function visiblePages(registrations: ModuleRegistration[], can: (permission: string) => boolean): PageRegistration[] {
  return registrations
    .flatMap((registration) => registration.pages)
    .filter((page) => can(page.requires))
    .sort((a, b) => a.order - b.order);
}
