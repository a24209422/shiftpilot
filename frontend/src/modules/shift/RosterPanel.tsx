import { useState, type FormEvent } from "react";
import { apiSend } from "../../api/client";
import type { Employee, ShiftRoster, ShiftType } from "../../api/types";
import { SelectField, TextField } from "../../forms/fields";
import { FormError } from "../../forms/FormError";
import { addDays, toLocalDate, weekStart } from "../../forms/time";
import { useSubmit } from "../../forms/useSubmit";
import { useToast } from "../../shell/Toast";
import { weekdayLabels } from "./labels";
import { useRosters, useShiftTypes } from "./queries";

const restValue = "rest";
const daysText = (roster: ShiftRoster) =>
  roster.days.length === 0 ? "全週休息" : roster.days.map((item) => `${weekdayLabels[item.weekday]} ${item.shiftName}`).join("、");

function RosterForm({ employee, types, onDone }: { employee: Employee; types: ShiftType[]; onDone(): void }) {
  const toast = useToast();
  const defaultId = types.find((item) => item.isDefault)?.id;
  // 預設從下週一生效、平日帶入預設班：換班表通常從新的一週開始
  const [effectiveFrom, setEffectiveFrom] = useState(() => toLocalDate(addDays(weekStart(new Date()), 7)));
  const [days, setDays] = useState<string[]>(() => weekdayLabels.map((_, index) => (index < 5 && defaultId ? String(defaultId) : restValue)));
  const save = useSubmit(
    () => apiSend("POST", "/api/shift/rosters", {
      employeeId: employee.id, effectiveFrom,
      days: days.flatMap((value, weekday) => (value === restValue ? [] : [{ weekday, shiftTypeId: Number(value) }])),
    }),
    { onSuccess: () => { toast("已新增週班表"); onDone(); }, invalidate: [["shifts"], ["leave"]] },
  );
  const options = [{ value: restValue, label: "休息" }, ...types.map((item) => ({ value: String(item.id), label: item.name }))];
  return (
    <form className="form" onSubmit={(event: FormEvent) => { event.preventDefault(); void save.submit(); }}>
      <TextField label="生效日" type="date" required value={effectiveFrom} onChange={setEffectiveFrom} error={save.fieldErrors.effectiveFrom} />
      {weekdayLabels.map((label, index) => (
        <SelectField key={label} label={label} value={days[index]} options={options}
          onChange={(value) => setDays((current) => current.map((item, position) => (position === index ? value : item)))} />
      ))}
      <FormError error={save.error} />
      <div className="formActions">
        <button className="primary" type="submit" disabled={save.pending}>儲存週班表</button>
        <button className="secondary" type="button" onClick={onDone}>取消</button>
      </div>
    </form>
  );
}

function DeleteRoster({ roster }: { roster: ShiftRoster }) {
  const toast = useToast();
  const remove = useSubmit(
    () => apiSend("DELETE", `/api/shift/rosters/${roster.id}`),
    { onSuccess: () => toast("已刪除週班表"), invalidate: [["shifts"], ["leave"]] },
  );
  return (
    <>
      <FormError error={remove.error} />
      <button className="danger" type="button" disabled={remove.pending} onClick={() => void remove.submit()}>刪除</button>
    </>
  );
}

export function RosterPanel({ employee, canEdit }: { employee: Employee; canEdit: boolean }) {
  const { data } = useRosters(employee.id);
  const { data: types } = useShiftTypes();
  const [adding, setAdding] = useState(false);
  const today = toLocalDate(new Date());
  return (
    <div className="form">
      {(data ?? []).length === 0 && <div className="empty">沒有週班表，套用預設班</div>}
      {(data ?? []).map((roster) => (
        <div className="rosterItem" key={roster.id}>
          <div className="rosterFrom">{roster.effectiveFrom} 起</div>
          <div>{daysText(roster)}</div>
          {/* 已生效的班表是歷史紀錄，只能刪還沒生效的 */}
          {canEdit && roster.effectiveFrom > today && <DeleteRoster roster={roster} />}
        </div>
      ))}
      {/* 班別載入後才給新增：表單的預設班只在初始化時讀一次，沒載入會全部變成休息 */}
      {canEdit && types && !adding && <button className="primary" type="button" onClick={() => setAdding(true)}>新增週班表</button>}
      {canEdit && types && adding && <RosterForm employee={employee} types={types} onDone={() => setAdding(false)} />}
    </div>
  );
}
