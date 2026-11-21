import { apiGet } from "../../api/client";
import type { LeaveCalendarItem } from "../../api/types";
import type { TimelineItem, TimelineSource } from "../../timeline/types";

// 後端已經依每個人的班把假裁成片段，前端照畫，不再自己假設上班時間
export function toLeaveTimelineItems(items: LeaveCalendarItem[]): TimelineItem[] {
  return items.flatMap((item) => {
    const pending = item.status === "pending";
    return item.segments.map((segment, index) => ({
      key: `leave:${item.id}:${index}`,
      kind: "block" as const,
      subjectId: item.employeeId,
      startAt: segment.startAt,
      endAt: segment.endAt,
      label: `${item.leaveTypeName ?? "請假"}${pending ? "（待核准）" : ""}`,
      muted: pending,
      // 看不到假別的人也看不到詳情，不給連結
      link: item.leaveTypeName === null ? undefined : `/leave?id=${item.id}`,
    }));
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
    queryFn: async () => toLeaveTimelineItems(await apiGet<LeaveCalendarItem[]>("/api/leave/calendar", { from, to })),
  }),
};
