import type { ApiError } from "../../api/client";
import type { MeetingConflict } from "../../api/types";
import { formatRange } from "../../forms/time";

// 請假時段撞到會議只是警告：列出會議，使用者確認後帶 acknowledgeWarnings 重送
export function MeetingWarning({ error, pending, onOverride }: { error: ApiError | null; pending: boolean; onOverride(): void }) {
  if (error?.code !== "MEETING_CONFLICT") return null;
  const conflicts = ((error.details as { conflicts?: MeetingConflict[] } | null)?.conflicts ?? []);
  return (
    <div className="formWarn" role="alert">
      這段時間你有會議：
      <ul>
        {conflicts.map((item) => <li key={item.bookingId}>{item.title}（{formatRange(item.startAt, item.endAt)}）</li>)}
      </ul>
      <button className="primary" type="button" disabled={pending} onClick={onOverride}>仍要送出</button>
    </div>
  );
}
