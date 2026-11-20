import type { ApiError } from "../../api/client";
import type { ParticipantConflict, ResourceConflict } from "../../api/types";
import { formatRange } from "../../forms/time";

interface Props { error: ApiError | null; onOverride(): void; pending: boolean }

// 資源撞期：擋下，沒有「仍要排」。參加者不方便：警告，使用者確認後帶 acknowledgeWarnings 重送
export function ConflictNotice({ error, onOverride, pending }: Props) {
  if (!error) return null;
  const conflicts = ((error.details as { conflicts?: unknown[] } | null)?.conflicts ?? []);
  if (error.code === "RESOURCE_CONFLICT") {
    return (
      <div className="formError" role="alert">
        資源在這個時段已被預約，沒辦法排：
        <ul>
          {(conflicts as ResourceConflict[]).map((item) => (
            <li key={`${item.bookingId}-${item.resourceId}`}>{item.resourceName}：{item.title}（{formatRange(item.startAt, item.endAt)}）</li>
          ))}
        </ul>
      </div>
    );
  }
  if (error.code === "PARTICIPANT_CONFLICT") {
    return (
      <div className="formWarn" role="alert">
        有參加者在這個時段不方便：
        <ul>
          {(conflicts as ParticipantConflict[]).map((item, index) => (
            <li key={`${item.employeeId}-${index}`}>
              {item.name}：{item.reason}{item.title && item.startAt && item.endAt ? `（${item.title}，${formatRange(item.startAt, item.endAt)}）` : ""}
            </li>
          ))}
        </ul>
        <button className="primary" type="button" disabled={pending} onClick={onOverride}>仍要排</button>
      </div>
    );
  }
  return null;
}
