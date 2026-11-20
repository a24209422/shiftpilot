import { addDays, formatDay, formatRange, formatTime, toInputValue, toLocalDate, toLocalString, weekStart } from "./time";

test("testFormatPartsFromBackendStrings", () => {
  expect(formatDay("2026-11-16T10:00:00")).toBe("11/16（一）");
  expect(formatTime("2026-11-16T10:05:00")).toBe("10:05");
  expect(toInputValue("2026-11-16T10:00:00")).toBe("2026-11-16T10:00");
});

test("testFormatRangeSameDay", () => {
  expect(formatRange("2026-11-16T10:00:00", "2026-11-16T11:00:00")).toBe("11/16（一） 10:00–11:00");
});

test("testFormatRangeCrossesMidnight", () => {
  expect(formatRange("2026-11-22T22:00:00", "2026-11-23T06:00:00")).toBe("11/22（日） 22:00 – 11/23（一） 06:00");
});

test("testWeekStartIsLocalMonday", () => {
  expect(toLocalString(weekStart(new Date(2026, 10, 22, 23, 30)))).toBe("2026-11-16T00:00");
  expect(toLocalString(weekStart(new Date(2026, 10, 23, 0, 0)))).toBe("2026-11-23T00:00");
});

test("testToLocalStringDoesNotShiftToUtc", () => {
  expect(toLocalString(new Date(2026, 0, 1, 0, 5))).toBe("2026-01-01T00:05");
  expect(toLocalDate(new Date(2026, 0, 1, 0, 5))).toBe("2026-01-01");
  expect(toLocalDate(addDays(new Date(2026, 11, 31), 1))).toBe("2027-01-01");
});
