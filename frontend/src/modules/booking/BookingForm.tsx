import { useRef, useState, type FormEvent } from "react";
import { apiSend } from "../../api/client";
import type { Booking } from "../../api/types";
import { useAuth } from "../../auth/AuthProvider";
import { CheckList, SelectField, TextArea, TextField } from "../../forms/fields";
import { FormError } from "../../forms/FormError";
import { toInputValue, toLocalString } from "../../forms/time";
import { useSubmit } from "../../forms/useSubmit";
import { useToast } from "../../shell/Toast";
import { useEmployees } from "../org/queries";
import { ConflictNotice } from "./ConflictNotice";
import { useResources } from "./queries";

const sameSet = (a: string[], b: string[]) => a.length === b.length && a.every((item) => b.includes(item));

function defaultTimes(): [string, string] {
  // 預設從下一個整點開始、一小時
  const now = new Date();
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate(), now.getHours() + 1, 0);
  const end = new Date(start.getFullYear(), start.getMonth(), start.getDate(), start.getHours() + 1, 0);
  return [toLocalString(start), toLocalString(end)];
}

export function BookingForm({ booking, onDone }: { booking?: Booking; onDone(): void }) {
  const toast = useToast();
  const { user } = useAuth();
  const { data: resourceData } = useResources(false);
  const { data: employeeData } = useEmployees();

  const original = booking && {
    organizerId: String(booking.participants.find((item) => item.role === "organizer")?.employeeId ?? ""),
    attendeeIds: booking.participants.filter((item) => item.role === "attendee").map((item) => String(item.employeeId)),
    resourceIds: booking.resources.map((item) => String(item.id)),
    startAt: toInputValue(booking.startAt),
    endAt: toInputValue(booking.endAt),
  };
  const [defaultStart, defaultEnd] = booking ? ["", ""] : defaultTimes();

  const [title, setTitle] = useState(booking?.title ?? "");
  const [category, setCategory] = useState(booking?.category ?? "");
  const [startAt, setStartAt] = useState(original?.startAt ?? defaultStart);
  const [endAt, setEndAt] = useState(original?.endAt ?? defaultEnd);
  const [resourceIds, setResourceIds] = useState<string[]>(original?.resourceIds ?? []);
  // 沒有對應員工的帳號（例如管理員）不能預設自己，要明確選主辦人
  const [organizerId, setOrganizerId] = useState(original?.organizerId ?? (user?.employeeId ? String(user.employeeId) : ""));
  const [attendeeIds, setAttendeeIds] = useState<string[]>(original?.attendeeIds ?? []);
  const [note, setNote] = useState(booking?.note ?? "");
  const [organizerMissing, setOrganizerMissing] = useState(false);
  // 「仍要排」只對下一次送出有效，不會悄悄套用到之後改過的內容
  const acknowledge = useRef(false);

  const activeResources = resourceData ?? [];
  const resourceOptions = [
    ...activeResources.map((item) => ({ value: String(item.id), label: item.name })),
    ...(booking?.resources ?? [])
      .filter((item) => !activeResources.some((active) => active.id === item.id))
      .map((item) => ({ value: String(item.id), label: `${item.name}（已停用）` })),
  ];
  const employees = employeeData ?? [];
  const employeeOptions = [
    ...employees.map((item) => ({ value: String(item.id), label: item.name })),
    ...(booking?.participants ?? [])
      .filter((item) => !employees.some((active) => active.id === item.employeeId))
      .map((item) => ({ value: String(item.employeeId), label: `${item.name}（已停用）` })),
  ];

  const { submit, pending, error, fieldErrors } = useSubmit(
    () => {
      const ack = acknowledge.current;
      acknowledge.current = false;
      if (!booking || !original) {
        return apiSend("POST", "/api/booking/bookings", {
          title, category, startAt, endAt,
          resourceIds: resourceIds.map(Number),
          participantEmployeeIds: attendeeIds.map(Number),
          organizerEmployeeId: Number(organizerId),
          note: note || null,
          acknowledgeWarnings: ack,
        });
      }
      // 只送改過的欄位；有改主辦人時，參加者也要一起送，名單才會跟畫面上看到的一致
      const changed: Record<string, unknown> = {};
      if (title !== booking.title) changed.title = title;
      if (category !== booking.category) changed.category = category;
      if (startAt !== original.startAt) changed.startAt = startAt;
      if (endAt !== original.endAt) changed.endAt = endAt;
      if (!sameSet(resourceIds, original.resourceIds)) changed.resourceIds = resourceIds.map(Number);
      const organizerChanged = organizerId !== original.organizerId;
      if (organizerChanged) changed.organizerEmployeeId = Number(organizerId);
      if (organizerChanged || !sameSet(attendeeIds, original.attendeeIds)) changed.participantEmployeeIds = attendeeIds.map(Number);
      if (note !== (booking.note ?? "")) changed.note = note || null;
      if (Object.keys(changed).length === 0) return Promise.resolve(undefined);
      if (ack) changed.acknowledgeWarnings = true;
      return apiSend("PATCH", `/api/booking/bookings/${booking.id}`, changed);
    },
    { onSuccess: () => { toast(booking ? "已更新排程" : "已新增排程"); onDone(); }, invalidate: [["bookings"], ["summary"]] },
  );

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!organizerId) {
      setOrganizerMissing(true);
      return;
    }
    setOrganizerMissing(false);
    void submit();
  }

  return (
    <form className="form" onSubmit={onSubmit}>
      <TextField label="標題" required value={title} onChange={setTitle} error={fieldErrors.title} />
      <TextField label="類別" required value={category} onChange={setCategory} error={fieldErrors.category} />
      <TextField label="開始" type="datetime-local" required value={startAt} onChange={setStartAt} error={fieldErrors.startAt} />
      <TextField label="結束" type="datetime-local" required value={endAt} onChange={setEndAt} error={fieldErrors.endAt} />
      <CheckList label="資源" options={resourceOptions} values={resourceIds} onChange={setResourceIds} error={fieldErrors.resourceIds} />
      <SelectField
        label="主辦人" value={organizerId} onChange={setOrganizerId} options={employeeOptions} allowEmpty="請選擇"
        error={organizerMissing ? "請選擇主辦人" : fieldErrors.organizerEmployeeId}
      />
      <CheckList
        label="參加者" options={employeeOptions.filter((item) => item.value !== organizerId)} values={attendeeIds}
        onChange={setAttendeeIds} error={fieldErrors.participantEmployeeIds}
      />
      <TextArea label="備註" value={note} onChange={setNote} error={fieldErrors.note} />
      <ConflictNotice error={error} pending={pending} onOverride={() => { acknowledge.current = true; void submit(); }} />
      <FormError error={error} />
      <div className="formActions">
        <button className="primary" type="submit" disabled={pending}>儲存</button>
        <button className="secondary" type="button" onClick={onDone}>取消</button>
      </div>
    </form>
  );
}
