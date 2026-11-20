import type { LeaveRequest } from "../../api/types";

export const leaveRequest = (overrides: Partial<LeaveRequest> = {}): LeaveRequest => ({
  id: 5, employeeId: 2, employeeName: "林小美", leaveTypeId: 1, leaveTypeName: "特休", startAt: "2026-11-24T09:00:00", endAt: "2026-11-24T18:00:00",
  hours: 8, reason: "家裡有事", status: "pending", decidedBy: null, decidedByName: null, decidedAt: null, decisionNote: null,
  cancelledBy: null, cancelledAt: null, createdBy: 1, createdAt: "2026-11-19T08:00:00", ...overrides,
});
