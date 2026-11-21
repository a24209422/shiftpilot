import type { ScheduleDay } from "../../api/types";
import { toShiftTimelineItems } from "./timeline";

const day = (overrides: Partial<ScheduleDay>): ScheduleDay => ({
  employeeId: 2, day: "2026-11-24", source: "default", shiftTypeId: 1, shiftName: "標準班",
  startAt: "2026-11-24T09:00:00", endAt: "2026-11-24T18:00:00", breakStartAt: "2026-11-24T12:00:00", breakEndAt: "2026-11-24T13:00:00",
  holidayName: null, overrideNote: null, ...overrides,
});

test("testShiftItemsSplitAtBreak", () => {
  expect(toShiftTimelineItems([day({})])).toEqual([
    { key: "shift:2:2026-11-24:0", kind: "status", subjectId: 2, startAt: "2026-11-24T09:00:00", endAt: "2026-11-24T12:00:00", label: "標準班" },
    { key: "shift:2:2026-11-24:1", kind: "status", subjectId: 2, startAt: "2026-11-24T13:00:00", endAt: "2026-11-24T18:00:00", label: "標準班" },
  ]);
});

test("testRestDaysAndShiftsWithoutBreak", () => {
  expect(toShiftTimelineItems([day({ source: "off", shiftTypeId: null, shiftName: null, startAt: null, endAt: null, breakStartAt: null, breakEndAt: null })])).toEqual([]);
  expect(toShiftTimelineItems([day({ breakStartAt: null, breakEndAt: null })])).toHaveLength(1);
});
