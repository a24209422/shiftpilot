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

export type QuotaKind = "seniority" | "yearly_cap" | "none";
export interface LeaveType { id: number; code: string; name: string; paidRatio: number; quotaKind: QuotaKind; annualCapHours: number | null; isActive: boolean }
export interface LeaveBalance {
  leaveTypeId: number; leaveTypeName: string; quotaKind: QuotaKind; periodStart: string | null; periodEnd: string | null;
  quotaHours: number | null; adjustmentHours: number; approvedHours: number; pendingHours: number; remainingHours: number | null;
}
export type LeaveStatus = "pending" | "approved" | "rejected" | "withdrawn" | "cancelled";
export interface LeaveRequest {
  id: number; employeeId: number; employeeName: string; leaveTypeId: number; leaveTypeName: string; startAt: string; endAt: string;
  hours: number; reason: string; status: LeaveStatus; decidedBy: number | null; decidedByName: string | null; decidedAt: string | null;
  decisionNote: string | null; cancelledBy: number | null; cancelledAt: string | null; createdBy: number; createdAt: string;
}
export interface MeetingConflict { bookingId: number; title: string; startAt: string; endAt: string }
export interface LeaveQuote { hours: number; remainingAfter: number | null; conflicts: MeetingConflict[] }
export interface LeaveAdjustment {
  id: number; employeeId: number; leaveTypeId: number; leaveTypeName: string; periodStart: string; hours: number; reason: string;
  createdBy: number; createdByEmail: string; createdAt: string;
}
export interface UnusedLeave {
  employeeId: number; employeeName: string; departmentName: string; periodStart: string; periodEnd: string;
  quotaHours: number; adjustmentHours: number; usedHours: number; unusedHours: number;
}
export interface LeaveCalendarItem { id: number; employeeId: number; startAt: string; endAt: string; status: "pending" | "approved"; leaveTypeName: string | null; segments: { startAt: string; endAt: string }[] }

export interface ShiftType {
  id: number; code: string; name: string; startTime: string; endTime: string;
  breakStart: string | null; breakEnd: string | null; isDefault: boolean; isActive: boolean;
}
export interface ShiftRosterDay { weekday: number; shiftTypeId: number; shiftName: string }
export interface ShiftRoster { id: number; employeeId: number; effectiveFrom: string; days: ShiftRosterDay[]; createdBy: number; createdAt: string }
export interface ShiftOverride {
  id: number; employeeId: number; day: string; shiftTypeId: number | null; shiftName: string | null; note: string;
  createdBy: number; createdAt: string; updatedBy: number; updatedAt: string;
}
export type ScheduleSource = "inactive" | "override" | "holiday" | "roster" | "default" | "off";
export interface ScheduleDay {
  employeeId: number; day: string; source: ScheduleSource; shiftTypeId: number | null; shiftName: string | null;
  startAt: string | null; endAt: string | null; breakStartAt: string | null; breakEndAt: string | null;
  holidayName: string | null; overrideNote: string | null;
}

export interface QaModel { id: string; label: string; remote: boolean }
export type QaMode = "pipeline" | "agent" | "jev" | "assistant" | "assistant-jev";
export type QaIntentName = "query" | "booking" | "manageBooking" | "leave";
export interface QaIntent {
  name: QaIntentName | null; confidence: number | null; fallbackReason: string | null; reused: boolean; promptTokens: number | null; seconds: number;
  addedName?: QaIntentName | null; cardName?: QaIntentName | null;
}
export interface QaSettings { jevConfigured: boolean }
export const qaProgressStages = ["prepare", "route", "intent", "generate_query", "query", "model", "tool", "proposal", "compose"] as const;
export type QaProgressStage = (typeof qaProgressStages)[number];
export type QaProgressStep = {
  type: "step"; id: number; stage: QaProgressStage; state: "running" | "done" | "failed"; tool?: string;
};
export type QaProgressEvent = { type: "accepted" } | QaProgressStep;
export type QaStreamEvent = QaProgressEvent
  | { type: "result"; answer: QaAnswer }
  | { type: "error"; status: number; error: { code: string; message: string; details?: unknown } };
export interface QaProposal {
  kind: "booking.create" | "booking.reschedule" | "booking.cancel" | "leave.create" | "leave.withdraw";
  request: { method: "POST" | "PATCH"; path: string; body: Record<string, unknown> | null };
  summary: { label: string; value: string }[];
  quote: { path: string; body: Record<string, unknown> } | null;
}
export interface QaHistoryItem { role: "user" | "assistant"; content: string }
export interface QaRoute { tool: string | null; confidence: number | null; fallbackReason: string | null; promptTokens: number | null; seconds: number }
export interface QaStep { tool: string; arguments: Record<string, unknown> | null; rowCount: number | null; error: string | null }
export interface QaAnswer {
  answer: string; sql: string; columns: string[]; rows: unknown[][]; truncated: boolean;
  model: string; remote: boolean; window: { from: string; to: string };
  mode: QaMode; steps?: QaStep[]; route?: QaRoute; proposal?: QaProposal | null; intent?: QaIntent;
}
