import { apiGet } from "../../api/client";
import type { Booking, Resource, ResourceKind } from "../../api/types";
import type { TimelineItem, TimelineSource, TimelineSubject, TimelineView } from "../../timeline/types";
import { resourceKindLabels } from "./labels";

const kindOrder: ResourceKind[] = ["room", "equipment", "vehicle"];

// 一筆排程用了幾個資源，就在幾列各出現一次
export function toTimelineItems(bookings: Booking[]): TimelineItem[] {
  return bookings.flatMap((booking) => booking.resources.map((resource) => ({
    key: `booking:${booking.id}@resource:${resource.id}`,
    kind: "event" as const,
    subjectId: resource.id,
    startAt: booking.startAt,
    endAt: booking.endAt,
    label: booking.title,
    link: `/bookings?week=${booking.startAt.slice(0, 10)}&id=${booking.id}`,
  })));
}

export function toResourceSubjects(resources: Resource[]): TimelineSubject[] {
  return resources
    .filter((resource) => resource.isActive)
    .sort((a, b) => kindOrder.indexOf(a.kind) - kindOrder.indexOf(b.kind) || a.name.localeCompare(b.name, "zh-Hant"))
    .map((resource) => ({ id: resource.id, label: resource.name, group: resourceKindLabels[resource.kind] }));
}

export const resourceTimelineView: TimelineView = {
  key: "resources",
  name: "資源",
  subjectType: "resource",
  requires: "booking.read",
  emptyText: "還沒有資源",
  // 不能跟 useResources 共用 queryKey：那邊快取的是 Resource[]，這裡是轉換後的列
  subjects: () => ({
    queryKey: ["resources", "timeline"],
    queryFn: async () => toResourceSubjects(await apiGet<Resource[]>("/api/booking/resources")),
  }),
  createRequires: "booking.write",
  createLink: (subjectId, startAt, endAt) =>
    `/bookings?${new URLSearchParams({ week: startAt.slice(0, 10), new: "1", resourceId: String(subjectId), startAt, endAt })}`,
};

export const bookingTimelineSource: TimelineSource = {
  key: "booking.bookings",
  name: "排程",
  subjectType: "resource",
  requires: "booking.read",
  // 放在 ["bookings", …] 底下：新增、修改、取消排程時現有的 invalidate 會順便更新時間軸
  items: (from, to) => ({
    queryKey: ["bookings", "timeline", from, to],
    queryFn: async () => toTimelineItems(await apiGet<Booking[]>("/api/booking/bookings", { from, to })),
  }),
};
