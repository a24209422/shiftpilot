import type { LeaveStatus, QuotaKind } from "../../api/types";

export const statusLabels: Record<LeaveStatus, string> = {
  pending: "待核准", approved: "已核准", rejected: "已退回", withdrawn: "已撤回", cancelled: "已取消",
};
export const statusTones: Record<LeaveStatus, string> = {
  pending: "warn", approved: "ok", rejected: "mute", withdrawn: "mute", cancelled: "mute",
};
export const quotaKindLabels: Record<QuotaKind, string> = { seniority: "依年資（特休）", yearly_cap: "年度上限", none: "不限" };
