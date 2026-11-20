import { useState, type FormEvent } from "react";
import { apiSend } from "../../api/client";
import type { CalendarDay } from "../../api/types";
import { SelectField, TextField } from "../../forms/fields";
import { FormError } from "../../forms/FormError";
import { useSubmit } from "../../forms/useSubmit";
import { useToast } from "../../shell/Toast";

export const calendarKindLabels: Record<CalendarDay["kind"], string> = { holiday: "放假", makeup_workday: "補班" };
const kindOptions = (Object.keys(calendarKindLabels) as CalendarDay["kind"][]).map((value) => ({ value, label: calendarKindLabels[value] }));

export function CalendarDayForm({ day, onDone }: { day?: CalendarDay; onDone(): void }) {
  const toast = useToast();
  const [date, setDate] = useState(day?.day ?? "");
  const [kind, setKind] = useState<string>(day?.kind ?? "holiday");
  const [name, setName] = useState(day?.name ?? "");

  const { submit, pending, error, fieldErrors } = useSubmit(
    // PUT 以日期為鍵：新增與修改是同一個動作
    () => apiSend("PUT", `/api/org/calendarDays/${date}`, { kind, name }),
    { onSuccess: () => { toast("已儲存日期"); onDone(); }, invalidate: [["calendarDays"]] },
  );

  return (
    <form className="form" onSubmit={(event: FormEvent) => { event.preventDefault(); void submit(); }}>
      {/* 編輯時日期唯讀：改日期等於換一筆，應該是刪除再新增 */}
      <TextField label="日期" type="date" required value={date} onChange={setDate} disabled={Boolean(day)} error={fieldErrors.day} />
      <SelectField label="種類" value={kind} onChange={setKind} options={kindOptions} error={fieldErrors.kind} />
      <TextField label="名稱" required value={name} onChange={setName} error={fieldErrors.name} />
      <FormError error={error} />
      <div className="formActions">
        <button className="primary" type="submit" disabled={pending}>儲存</button>
        <button className="secondary" type="button" onClick={onDone}>取消</button>
      </div>
    </form>
  );
}
