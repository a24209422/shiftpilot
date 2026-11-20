export type Role = "employee" | "manager" | "hr" | "admin";
export interface CurrentUser { id: number; email: string; role: Role; employeeId: number | null; employeeName: string | null }
export interface VisibleModule { name: string; title: string; permissions: string[] }

export type ResourceKind = "room" | "equipment" | "vehicle";
export interface Resource {
  id: number; name: string; kind: ResourceKind; location: string | null; capacity: number | null;
  features: string[]; isActive: boolean; note: string | null;
}
export interface Booking {
  id: number; title: string; category: string; startAt: string; endAt: string; status: "confirmed" | "cancelled";
  note: string | null; createdBy: number; createdAt: string;
  resources: { id: number; name: string; kind: ResourceKind }[];
  participants: { employeeId: number; name: string; role: "organizer" | "attendee" }[];
}
export interface BookingSummary {
  todayBookings: Booking[];
  nextBooking: Booking | null;
  resourceStatus: { resourceId: number; name: string; kind: ResourceKind; currentBooking: Booking | null }[];
  // 還沒結束的已確認排程數
  bookingCount: number;
  resourceCount: number;
}
export interface Department { id: number; name: string; parentId: number | null }
export interface Employee {
  id: number; employeeNo: string; name: string; email: string | null; departmentId: number; jobTitle: string;
  managerId: number | null; hiredOn: string; isActive: boolean; leftOn: string | null;
}
export interface CalendarDay { day: string; kind: "holiday" | "makeup_workday"; name: string }
export interface User {
  id: number; email: string; role: Role; employeeId: number | null; employeeName: string | null;
  isActive: boolean; lastLoginAt: string | null; lockedUntil: string | null; createdAt: string;
}
export interface AuditEntry {
  id: number; at: string; userId: number | null; module: string; action: string; entity: string; entityId: string;
  before: unknown; after: unknown;
}

export interface ResourceConflict { bookingId: number; title: string; startAt: string; endAt: string; resourceId: number; resourceName: string }
export interface ParticipantConflict {
  employeeId: number; name: string; reason: string; bookingId?: number; title?: string; startAt?: string; endAt?: string;
}
