import { toLeaveTimelineItems } from "./timeline";

test("testLeaveItemsFollowSegments", () => {
  const items = toLeaveTimelineItems([
    {
      id: 5, employeeId: 2, startAt: "2026-11-24T09:00:00", endAt: "2026-11-24T18:00:00", status: "approved", leaveTypeName: "事假",
      segments: [{ startAt: "2026-11-24T09:00:00", endAt: "2026-11-24T12:00:00" }, { startAt: "2026-11-24T13:00:00", endAt: "2026-11-24T18:00:00" }],
    },
    { id: 6, employeeId: 3, startAt: "2026-11-28T09:00:00", endAt: "2026-11-28T18:00:00", status: "pending", leaveTypeName: null, segments: [] },
  ]);
  expect(items).toEqual([
    { key: "leave:5:0", kind: "block", subjectId: 2, startAt: "2026-11-24T09:00:00", endAt: "2026-11-24T12:00:00", label: "事假", muted: false, link: "/leave?id=5" },
    { key: "leave:5:1", kind: "block", subjectId: 2, startAt: "2026-11-24T13:00:00", endAt: "2026-11-24T18:00:00", label: "事假", muted: false, link: "/leave?id=5" },
  ]);
});

test("testHiddenLeaveTypeHasNoLink", () => {
  const [item] = toLeaveTimelineItems([
    { id: 6, employeeId: 3, startAt: "2026-11-24T13:00:00", endAt: "2026-11-24T18:00:00", status: "pending", leaveTypeName: null, segments: [{ startAt: "2026-11-24T13:00:00", endAt: "2026-11-24T18:00:00" }] },
  ]);
  expect(item.label).toBe("請假（待核准）");
  expect(item.link).toBeUndefined();
  expect(item.muted).toBe(true);
});
