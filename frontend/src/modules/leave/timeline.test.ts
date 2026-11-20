import { clipToWorkday, toLeaveTimelineItems } from "./timeline";

test("testClipToWorkdayKeepsOnlyWorkHoursOfThatDay", () => {
  const item = { startAt: "2026-11-23T09:00:00", endAt: "2026-11-25T18:00:00" };
  expect(clipToWorkday(item, "2026-11-24")).toEqual({ startAt: "2026-11-24T09:00:00", endAt: "2026-11-24T18:00:00" });
  expect(clipToWorkday({ startAt: "2026-11-24T13:00:00", endAt: "2026-11-24T15:00:00" }, "2026-11-24")).toEqual({ startAt: "2026-11-24T13:00:00", endAt: "2026-11-24T15:00:00" });
  expect(clipToWorkday({ startAt: "2026-11-24T18:00:00", endAt: "2026-11-25T09:00:00" }, "2026-11-24")).toBeNull();
});

test("testLeaveItemsLabelAndLink", () => {
  const items = toLeaveTimelineItems([
    { id: 5, employeeId: 2, startAt: "2026-11-24T09:00:00", endAt: "2026-11-24T18:00:00", status: "approved", leaveTypeName: "事假" },
    { id: 6, employeeId: 3, startAt: "2026-11-24T13:00:00", endAt: "2026-11-24T18:00:00", status: "pending", leaveTypeName: null },
  ], "2026-11-24T00:00");
  expect(items).toEqual([
    { key: "leave:5", kind: "block", subjectId: 2, startAt: "2026-11-24T09:00:00", endAt: "2026-11-24T18:00:00", label: "事假", muted: false, link: "/leave?id=5" },
    { key: "leave:6", kind: "block", subjectId: 3, startAt: "2026-11-24T13:00:00", endAt: "2026-11-24T18:00:00", label: "請假（待核准）", muted: true, link: undefined },
  ]);
});
