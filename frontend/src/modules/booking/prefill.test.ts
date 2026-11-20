import { readPrefill } from "./prefill";

const read = (query: string) => readPrefill(new URLSearchParams(query));

test("testReadsValidPrefill", () => {
  expect(read("resourceId=1&startAt=2026-11-20T14:00&endAt=2026-11-20T15:00"))
    .toEqual({ resourceId: "1", startAt: "2026-11-20T14:00", endAt: "2026-11-20T15:00" });
});

test("testIgnoresNonNumericResource", () => {
  expect(read("resourceId=abc&startAt=2026-11-20T14:00&endAt=2026-11-20T15:00"))
    .toEqual({ startAt: "2026-11-20T14:00", endAt: "2026-11-20T15:00" });
});

test("testIgnoresBothTimesWhenEitherIsInvalid", () => {
  expect(read("resourceId=1&startAt=2026-02-30T10:00&endAt=2026-03-01T11:00")).toEqual({ resourceId: "1" });
  expect(read("resourceId=1&startAt=2026-11-20T14:00&endAt=tomorrow")).toEqual({ resourceId: "1" });
  expect(read("resourceId=1&startAt=2026-11-20T14:00")).toEqual({ resourceId: "1" });
});

test("testIgnoresTimesWhenEndIsNotAfterStart", () => {
  expect(read("startAt=2026-11-20T15:00&endAt=2026-11-20T14:00")).toEqual({});
  expect(read("startAt=2026-11-20T15:00&endAt=2026-11-20T15:00")).toEqual({});
});
