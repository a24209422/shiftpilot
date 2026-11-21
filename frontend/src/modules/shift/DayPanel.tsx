import { useState, type FormEvent } from "react";
import { apiSend } from "../../api/client";
import type { Employee, ScheduleDay } from "../../api/types";
import { SelectField, TextArea } from "../../forms/fields";
import { FormError } from "../../forms/FormError";
import { formatDay, formatRange } from "../../forms/time";
import { useSubmit } from "../../forms/useSubmit";
import { DetailList } from "../../shell/DetailList";
import { useToast } from "../../shell/Toast";
import { sourceLabels } from "./labels";
import { useShiftTypes } from "./queries";

const restValue = "rest";

function OverrideForm({ day, onDone }: { day: ScheduleDay; onDone(): void }) {
  const toast = useToast();
  const { data: types } = useShiftTypes();
  const [shiftValue, setShiftValue] = useState(day.source === "override" && day.shiftTypeId === null ? restValue : String(day.shiftTypeId ?? restValue));
  const [note, setNote] = useState(day.overrideNote ?? "");
  const save = useSubmit(
    () => apiSend("PUT", "/api/shift/overrides", {
      employeeId: day.employeeId, day: day.day, shiftTypeId: shiftValue === restValue ? null : Number(shiftValue), note,
    }),
    { onSuccess: () => { toast("已設定單日調整"); onDone(); }, invalidate: [["shifts"]] },
  );
  const remove = useSubmit(
    () => apiSend("DELETE", `/api/shift/overrides/${day.employeeId}/${day.day}`),
    { onSuccess: () => { toast("已刪除調整"); onDone(); }, invalidate: [["shifts"]] },
  );
  const options = [{ value: restValue, label: "休息" }, ...(types ?? []).map((item) => ({ value: String(item.id), label: item.name }))];
  return (
    <form className="form" onSubmit={(event: FormEvent) => { event.preventDefault(); void save.submit(); }}>
      <SelectField label="班別" value={shiftValue} onChange={setShiftValue} options={options} error={save.fieldErrors.shiftTypeId} />
      <TextArea label="備註" value={note} onChange={setNote} />
      <FormError error={save.error ?? remove.error} />
      <div className="formActions">
        <button className="primary" type="submit" disabled={save.pending}>設定單日調整</button>
        {day.source === "override" && <button className="danger" type="button" disabled={remove.pending} onClick={() => void remove.submit()}>刪除調整</button>}
      </div>
    </form>
  );
}

export function DayPanel({ day, employee, canEdit, onDone }: { day: ScheduleDay; employee: Employee; canEdit: boolean; onDone(): void }) {
  const shiftText = day.shiftName && day.startAt && day.endAt ? `${day.shiftName}（${formatRange(day.startAt, day.endAt)}）` : day.source === "inactive" ? "—" : "休息";
  return (
    <>
      <DetailList
        items={[
          ["員工", employee.name],
          ["日期", formatDay(day.day)],
          ["班", shiftText],
          ["來源", sourceLabels[day.source]],
          ["假日", day.holidayName ?? "—"],
          ["備註", day.overrideNote || "—"],
        ]}
      />
      {/* 未在職的日子排了也不會生效，不給調整 */}
      {canEdit && day.source !== "inactive" && <OverrideForm key={`${day.employeeId}:${day.day}`} day={day} onDone={onDone} />}
    </>
  );
}
