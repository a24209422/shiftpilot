import type { Booking, Resource } from "../../api/types";
import { resourceTimelineView, toResourceSubjects, toTimelineItems } from "./timeline";

const resource = (id: number, name: string, kind: Resource["kind"], isActive = true): Resource => ({
  id, name, kind, location: null, capacity: null, features: [], isActive, note: null,
});

const booking: Booking = {
  id: 7, title: "團隊週會", category: "會議", startAt: "2026-11-20T10:00:00", endAt: "2026-11-20T11:00:00", status: "confirmed",
  note: null, createdBy: 1, createdAt: "2026-11-19T08:00:00",
  resources: [{ id: 1, name: "3F 大會議室", kind: "room" }, { id: 3, name: "投影機", kind: "equipment" }],
  participants: [],
};

test("testEachResourceOfBookingBecomesAnItem", () => {
  expect(toTimelineItems([booking])).toEqual([
    { key: "booking:7@resource:1", kind: "event", subjectId: 1, startAt: booking.startAt, endAt: booking.endAt, label: "團隊週會", link: "/bookings?week=2026-11-20&id=7" },
    { key: "booking:7@resource:3", kind: "event", subjectId: 3, startAt: booking.startAt, endAt: booking.endAt, label: "團隊週會", link: "/bookings?week=2026-11-20&id=7" },
  ]);
});

test("testResourceSubjectsSortedByKindThenName", () => {
  const subjects = toResourceSubjects([
    resource(3, "投影機", "equipment"),
    resource(2, "5F 小會議室", "room"),
    resource(4, "公務車 A", "vehicle"),
    resource(1, "3F 大會議室", "room"),
    resource(5, "舊會議室", "room", false),
  ]);
  expect(subjects).toEqual([
    { id: 1, label: "3F 大會議室", group: "會議室" },
    { id: 2, label: "5F 小會議室", group: "會議室" },
    { id: 3, label: "投影機", group: "設備" },
    { id: 4, label: "公務車 A", group: "公務車" },
  ]);
});

test("testCreateLinkPrefillsNewBooking", () => {
  const link = resourceTimelineView.createLink!(1, "2026-11-20T14:00", "2026-11-20T15:00");
  const [path, query] = link.split("?");
  expect(path).toBe("/bookings");
  expect(Object.fromEntries(new URLSearchParams(query))).toEqual({
    week: "2026-11-20", new: "1", resourceId: "1", startAt: "2026-11-20T14:00", endAt: "2026-11-20T15:00",
  });
});
