import { axisFor, clipToDay, groupSubjects, halfDayGroups, minuteLabel, minuteToLocal, parseDay, percentOf, slotFor, type Span } from "./layout";

const day = new Date(2026, 10, 20);
const span = (startMinute: number, endMinute: number): Span => ({ startMinute, endMinute, crossesDay: false });

test("testClipToDayKeepsItemInsideDay", () => {
  expect(clipToDay(day, { startAt: "2026-11-20T10:00:00", endAt: "2026-11-20T11:30:00" }))
    .toEqual({ startMinute: 600, endMinute: 690, crossesDay: false });
});

test("testClipToDayCutsCrossDayItems", () => {
  expect(clipToDay(day, { startAt: "2026-11-19T22:00:00", endAt: "2026-11-20T09:00:00" }))
    .toEqual({ startMinute: 0, endMinute: 540, crossesDay: true });
  expect(clipToDay(day, { startAt: "2026-11-20T23:00:00", endAt: "2026-11-21T02:00:00" }))
    .toEqual({ startMinute: 1380, endMinute: 1440, crossesDay: true });
});

test("testClipToDayDropsItemsOutsideDay", () => {
  expect(clipToDay(day, { startAt: "2026-11-19T10:00:00", endAt: "2026-11-20T00:00:00" })).toBeNull();
  expect(clipToDay(day, { startAt: "2026-11-21T00:00:00", endAt: "2026-11-21T01:00:00" })).toBeNull();
});

test("testAxisDefaultsToEightToTwenty", () => {
  expect(axisFor([])).toEqual({ startMinute: 480, endMinute: 1200 });
  expect(axisFor([span(600, 660)])).toEqual({ startMinute: 480, endMinute: 1200 });
});

test("testAxisExtendsToWholeHoursUpToFullDay", () => {
  expect(axisFor([span(450, 700), span(1100, 1290)])).toEqual({ startMinute: 420, endMinute: 1320 });
  expect(axisFor([span(0, 1440)])).toEqual({ startMinute: 0, endMinute: 1440 });
});

test("testPercentOf", () => {
  expect(percentOf({ startMinute: 480, endMinute: 1200 }, 840)).toBe(50);
  expect(percentOf({ startMinute: 480, endMinute: 1200 }, 480)).toBe(0);
});

test("testSlotIsOneHourWhenRowIsFree", () => {
  expect(slotFor(840, [])).toEqual({ startMinute: 840, endMinute: 900 });
});

test("testSlotEndsAtNextItem", () => {
  expect(slotFor(840, [span(870, 930)])).toEqual({ startMinute: 840, endMinute: 870 });
});

test("testSlotStartsAfterPreviousItem", () => {
  expect(slotFor(600, [span(600, 620)])).toEqual({ startMinute: 620, endMinute: 680 });
  expect(slotFor(600, [span(600, 620), span(620, 625)])).toEqual({ startMinute: 625, endMinute: 685 });
});

test("testSlotIsNullWhenCellIsCovered", () => {
  expect(slotFor(600, [span(590, 640)])).toBeNull();
});

test("testMinuteToLocalRollsOverToNextDay", () => {
  expect(minuteToLocal(day, 840)).toBe("2026-11-20T14:00");
  expect(minuteToLocal(day, 1470)).toBe("2026-11-21T00:30");
});

test("testMinuteLabel", () => {
  expect(minuteLabel(570)).toBe("09:30");
  expect(minuteLabel(1440)).toBe("24:00");
});

test("testHalfDayGroupsSplitAtNoon", () => {
  expect(halfDayGroups({ startMinute: 480, endMinute: 1200 })).toEqual([
    { label: "上午", startMinute: 480, endMinute: 780 },
    { label: "下午", startMinute: 780, endMinute: 1200 },
  ]);
  expect(halfDayGroups({ startMinute: 0, endMinute: 600 })).toEqual([{ label: "上午", startMinute: 0, endMinute: 600 }]);
  expect(halfDayGroups({ startMinute: 780, endMinute: 1440 })).toEqual([{ label: "下午", startMinute: 780, endMinute: 1440 }]);
});

test("testParseDayFallsBackToToday", () => {
  const now = new Date(2026, 10, 20, 9, 30);
  expect(parseDay("2026-11-21", now)).toEqual(new Date(2026, 10, 21));
  expect(parseDay(null, now)).toEqual(new Date(2026, 10, 20));
  expect(parseDay("2026-02-30", now)).toEqual(new Date(2026, 10, 20));
  expect(parseDay("abc", now)).toEqual(new Date(2026, 10, 20));
});

test("testGroupSubjectsKeepsOrder", () => {
  const groups = groupSubjects([
    { id: 1, label: "A", group: "會議室" },
    { id: 2, label: "B", group: "會議室" },
    { id: 3, label: "C", group: "設備" },
  ]);
  expect(groups.map((group) => [group.name, group.subjects.map((item) => item.id)])).toEqual([["會議室", [1, 2]], ["設備", [3]]]);
});
