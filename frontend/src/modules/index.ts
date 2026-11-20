import { bookingRegistration } from "./booking";
import type { ModuleRegistration } from "./registry";

// 新增一個模組的頁面 = 在 src/modules/<名稱>/index.ts 做一筆登記，再加到這裡；導覽列與首頁方塊會自己長出來
export const allRegistrations: ModuleRegistration[] = [bookingRegistration];
