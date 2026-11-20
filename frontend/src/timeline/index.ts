import { createElement } from "react";
import type { ModuleRegistration } from "../modules/registry";
import { TimelinePage } from "./TimelinePage";

// 時間軸彙整多個模組，所以由平台登記，不放進任何一個模組；
// 第一版只有資源檢視，顯示條件先用它需要的 booking.read，出現第二種檢視時改成「至少有一種看得到的檢視」
export function createTimelineRegistration(sources: ModuleRegistration[]): ModuleRegistration {
  return {
    pages: [{
      key: "timeline", path: "/timeline", name: "時間軸", en: "Timeline", icon: "timeline",
      requires: "booking.read", element: createElement(TimelinePage, { registrations: sources }), order: 15,
    }],
  };
}
