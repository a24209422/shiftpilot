import type { ScheduleDay } from "../../api/types";

export const hourOptions = Array.from({ length: 24 }, (_, hour) => {
  const value = `${String(hour).padStart(2, "0")}:00`;
  return { value, label: value };
});

export function shiftHours(type: { startTime: string; endTime: string }): string {
  // 下班時間不晚於上班時間就是跨過午夜
  const crosses = type.endTime <= type.startTime;
  return `${type.startTime}–${type.endTime}${crosses ? "（跨日）" : ""}`;
}

export function cellText(day: ScheduleDay): string {
  if (day.source === "inactive") return "—";
  if (day.shiftName && day.startAt && day.endAt) return `${day.shiftName} ${day.startAt.slice(11, 13)}–${day.endAt.slice(11, 13)}`;
  if (day.holidayName) return day.holidayName;
  return "休";
}
