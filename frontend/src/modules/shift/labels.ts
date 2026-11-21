import type { ScheduleSource } from "../../api/types";

export const sourceLabels: Record<ScheduleSource, string> = {
  inactive: "未在職", override: "單日調整", holiday: "國定假日", roster: "週班表", default: "預設班", off: "休息",
};
export const weekdayLabels = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"];
