import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, apiSend } from "../../api/client";
import type { LeaveQuote, MeetingConflict } from "../../api/types";
import { SelectField, TextArea, TextField } from "../../forms/fields";
import { FormError } from "../../forms/FormError";
import { formatRange, toLocalDate } from "../../forms/time";
import { useSubmit } from "../../forms/useSubmit";
import { useToast } from "../../shell/Toast";
import { useLeaveTypes } from "./queries";

// 等使用者停手再試算，避免每改一個欄位就打一次 API
const quoteDelay = 300;
const hourOptions = Array.from({ length: 10 }, (_, index) => {
  const value = `${String(9 + index).padStart(2, "0")}:00`;
  return { value, label: value };
});

function tomorrow(): string {
  const now = new Date();
  return toLocalDate(new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1));
}

function MeetingWarning({ error, pending, onOverride }: { error: ApiError | null; pending: boolean; onOverride(): void }) {
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

export function LeaveRequestForm({ onDone }: { onDone(): void }) {
  const toast = useToast();
  const { data: types } = useLeaveTypes();
  const [leaveTypeId, setLeaveTypeId] = useState("");
  const [startDate, setStartDate] = useState(tomorrow);
  const [startTime, setStartTime] = useState("09:00");
  const [endDate, setEndDate] = useState(tomorrow);
  const [endTime, setEndTime] = useState("18:00");
  const [reason, setReason] = useState("");
  const [quote, setQuote] = useState<LeaveQuote | null>(null);
  const [quoteError, setQuoteError] = useState<ApiError | null>(null);
  const startAt = `${startDate}T${startTime}`;
  const endAt = `${endDate}T${endTime}`;
  const inputKey = `${leaveTypeId}|${startAt}|${endAt}`;
  // 會議衝突是針對「送出當下」的假別與時段查的：記下那次的內容，改過之後衝突提示與「仍要送出」都不再成立
  const submittedKey = useRef<string | null>(null);
  // 「仍要送出」只認這一組內容，且用過就清掉；就算被重複送出的防呆擋下也不會殘留到之後的一般送出
  const acknowledgedKey = useRef<string | null>(null);

  useEffect(() => {
    setQuote(null);
    setQuoteError(null);
    if (!leaveTypeId || !startDate || !endDate) return;
    let stale = false;
    const timer = setTimeout(() => {
      apiSend<LeaveQuote>("POST", "/api/leave/requests/quote", { leaveTypeId: Number(leaveTypeId), startAt, endAt })
        .then((result) => { if (!stale) setQuote(result); })
        .catch((caught) => { if (!stale) setQuoteError(caught instanceof ApiError ? caught : new ApiError(0, "UNKNOWN", "試算失敗")); });
    }, quoteDelay);
    return () => { stale = true; clearTimeout(timer); };
  }, [leaveTypeId, startAt, endAt, startDate, endDate]);

  const { submit, pending, error, fieldErrors } = useSubmit(
    () => {
      const ack = acknowledgedKey.current === inputKey;
      acknowledgedKey.current = null;
      submittedKey.current = inputKey;
      return apiSend("POST", "/api/leave/requests", { leaveTypeId: Number(leaveTypeId), startAt, endAt, reason, acknowledgeWarnings: ack });
    },
    { onSuccess: () => { toast("已送出請假申請"); onDone(); }, invalidate: [["leave"]] },
  );

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void submit();
  }

  const conflictIsCurrent = error?.code === "MEETING_CONFLICT" && submittedKey.current === inputKey;
  const typeOptions = (types ?? []).map((item) => ({ value: String(item.id), label: item.name }));
  const quoteText = quote && `共 ${quote.hours} 小時${quote.remainingAfter === null ? "" : `，送出後剩 ${quote.remainingAfter} 小時`}`;

  return (
    <form className="form" onSubmit={onSubmit}>
      <SelectField label="假別" value={leaveTypeId} onChange={setLeaveTypeId} options={typeOptions} allowEmpty="請選擇" required error={fieldErrors.leaveTypeId} />
      <TextField label="開始日期" type="date" required value={startDate} onChange={setStartDate} />
      <SelectField label="開始時間" value={startTime} onChange={setStartTime} options={hourOptions} error={fieldErrors.startAt} />
      <TextField label="結束日期" type="date" required value={endDate} onChange={setEndDate} />
      <SelectField label="結束時間" value={endTime} onChange={setEndTime} options={hourOptions} error={fieldErrors.endAt} />
      <TextArea label="事由" value={reason} onChange={setReason} />
      {quoteText && <div className="formNote">{quoteText}</div>}
      {quote && quote.conflicts.length > 0 && (
        <div className="formWarn">這段時間你有會議：{[...new Set(quote.conflicts.map((item) => item.title))].join("、")}</div>
      )}
      <FormError error={quoteError} />
      {conflictIsCurrent && <MeetingWarning error={error} pending={pending} onOverride={() => { if (pending) return; acknowledgedKey.current = inputKey; void submit(); }} />}
      {!conflictIsCurrent && error?.code !== "MEETING_CONFLICT" && <FormError error={error} />}
      <div className="formActions">
        <button className="primary" type="submit" disabled={pending || quoteError !== null || !leaveTypeId}>送出</button>
        <button className="secondary" type="button" onClick={onDone}>取消</button>
      </div>
    </form>
  );
}
