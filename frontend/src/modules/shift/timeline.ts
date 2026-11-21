import { apiGet } from "../../api/client";
import type { ScheduleDay } from "../../api/types";
import { addDays, parseLocal, toLocalDate } from "../../forms/time";
import type { TimelineItem, TimelineSource } from "../../timeline/types";

export function toShiftTimelineItems(days: ScheduleDay[]): TimelineItem[] {
  return days.flatMap((day) => {
    if (!day.startAt || !day.endAt) return [];
    // 休息時間不算上班，底色在這裡斷開
    const windows = day.breakStartAt && day.breakEndAt
      ? [[day.startAt, day.breakStartAt], [day.breakEndAt, day.endAt]]
      : [[day.startAt, day.endAt]];
    return windows
      .filter(([startAt, endAt]) => startAt < endAt)
      .map(([startAt, endAt], index) => ({
        key: `shift:${day.employeeId}:${day.day}:${index}`, kind: "status" as const, subjectId: day.employeeId, startAt, endAt, label: day.shiftName ?? "",
      }));
  });
}

export const shiftTimelineSource: TimelineSource = {
  key: "shift.schedule",
  name: "班表",
  subjectType: "employee",
  requires: "shift.read",
  items: (from, to) => {
    // 前一晚的跨日班會延續到今天，所以從前一天查起；時間軸頁會把它裁到當天
    const day = parseLocal(from);
    return {
      queryKey: ["shifts", "timeline", from, to],
      queryFn: async () => toShiftTimelineItems(await apiGet<ScheduleDay[]>("/api/shift/schedule", {
        from: toLocalDate(addDays(day, -1)), to: toLocalDate(day),
      })),
    };
  },
};
