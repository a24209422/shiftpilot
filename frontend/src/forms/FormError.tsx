import type { ApiError } from "../api/client";

// 撞期與參加者警告由排程表單自己畫（要列出明細與「仍要排」），這裡不處理
const handledElsewhere = new Set(["RESOURCE_CONFLICT", "PARTICIPANT_CONFLICT"]);

export function FormError({ error }: { error: ApiError | null }) {
  if (!error || handledElsewhere.has(error.code)) return null;
  return <div className="formError" role="alert">{error.message}</div>;
}
