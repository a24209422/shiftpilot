import { apiGet } from "../../api/client";
import type { LeaveCalendarItem } from "../../api/types";
import type { TimelineItem, TimelineSource } from "../../timeline/types";

// 跟後端的固定上班時間一致；排班模組做好後改成依班表
const workStart = "09:00:00";
const workEnd = "18:00:00";

// 跨好幾天的假在中間那幾天會蓋滿 00:00–24:00，把時間軸撐成整天；裁到當天的上班時間才看得清楚
export function clipToWorkday(item: { startAt: string; endAt: string }, day: string): { startAt: string; endAt: string } | null {
  const windowStart = `${day}T${workStart}`;
  const windowEnd = `${day}T${workEnd}`;
  // 同格式的本地時間字串可以直接比大小
  const startAt = item.startAt > windowStart ? item.startAt : windowStart;
  const endAt = item.endAt < windowEnd ? item.endAt : windowEnd;
  return startAt < endAt ? { startAt, endAt } : null;
}

export function toLeaveTimelineItems(items: LeaveCalendarItem[], from: string): TimelineItem[] {
  const day = from.slice(0, 10);
  return items.flatMap((item) => {
    const clipped = clipToWorkday(item, day);
    if (!clipped) return [];
    const pending = item.status === "pending";
    return [{
      key: `leave:${item.id}`,
      kind: "block" as const,
      subjectId: item.employeeId,
      ...clipped,
      label: `${item.leaveTypeName ?? "請假"}${pending ? "（待核准）" : ""}`,
      muted: pending,
      // 看不到假別的人也看不到詳情，不給連結
      link: item.leaveTypeName === null ? undefined : `/leave?id=${item.id}`,
    }];
  });
}

export const leaveTimelineSource: TimelineSource = {
  key: "leave.calendar",
  name: "請假",
  subjectType: "employee",
  requires: "leave.request",
  // 放在 ["leave", …] 底下：送出、核准、取消時現有的 invalidate 會順便更新時間軸
  items: (from, to) => ({
    queryKey: ["leave", "timeline", from, to],
    queryFn: async () => toLeaveTimelineItems(await apiGet<LeaveCalendarItem[]>("/api/leave/calendar", { from, to }), from),
  }),
};
