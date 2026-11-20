import { createElement } from "react";
import type { ModuleRegistration } from "../modules/registry";
import { TimelinePage } from "./TimelinePage";

// 時間軸彙整多個模組，所以由平台登記，不放進任何一個模組；
// 顯示條件用 booking.read：所有角色都同時有 booking.read 與 org.read，各檢視自己再依 requires 篩選
export function createTimelineRegistration(sources: ModuleRegistration[]): ModuleRegistration {
  return {
    pages: [{
      key: "timeline", path: "/timeline", name: "時間軸", en: "Timeline", icon: "timeline",
      requires: "booking.read", element: createElement(TimelinePage, { registrations: sources }), order: 15,
    }],
  };
}
