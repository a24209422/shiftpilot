import { createTimelineRegistration } from "../timeline";
import { bookingRegistration } from "./booking";
import { coreRegistration } from "./core";
import { orgRegistration } from "./org";
import type { ModuleRegistration } from "./registry";

// 新增一個模組的頁面 = 在 src/modules/<名稱>/index.ts 做一筆登記，再加到這裡；導覽列與首頁方塊會自己長出來
const moduleRegistrations: ModuleRegistration[] = [bookingRegistration, orgRegistration, coreRegistration];

// 時間軸要讀所有模組登記的檢視與來源，所以放在最後組起來
export const allRegistrations: ModuleRegistration[] = [...moduleRegistrations, createTimelineRegistration(moduleRegistrations)];
