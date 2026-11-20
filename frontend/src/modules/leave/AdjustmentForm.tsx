import { useEffect, useState, type FormEvent } from "react";
import { apiSend } from "../../api/client";
import { SelectField, TextArea, TextField } from "../../forms/fields";
import { FormError } from "../../forms/FormError";
import { useSubmit } from "../../forms/useSubmit";
import { useToast } from "../../shell/Toast";
import { useLeaveBalances, useLeaveTypes } from "./queries";

export function AdjustmentForm({ employeeId, onDone }: { employeeId: number; onDone(): void }) {
  const toast = useToast();
  const { data: types } = useLeaveTypes();
  const { data: balances } = useLeaveBalances(employeeId);
  const [leaveTypeId, setLeaveTypeId] = useState("");
  const [periodStart, setPeriodStart] = useState("");
  const [hours, setHours] = useState("");
  const [reason, setReason] = useState("");

  // 帶入這位員工這個假別「目前」的年度開始日；要調過去的年度可以自己改
  useEffect(() => {
    const balance = balances?.find((item) => String(item.leaveTypeId) === leaveTypeId);
    if (balance?.periodStart) setPeriodStart(balance.periodStart);
  }, [leaveTypeId, balances]);

  const { submit, pending, error, fieldErrors } = useSubmit(
    () => apiSend("POST", "/api/leave/adjustments", { employeeId, leaveTypeId: Number(leaveTypeId), periodStart, hours: Number(hours), reason }),
    { onSuccess: () => { toast("已新增額度調整"); onDone(); }, invalidate: [["leave"]] },
  );
  const options = (types ?? []).filter((item) => item.quotaKind !== "none").map((item) => ({ value: String(item.id), label: item.name }));
  return (
    <form className="form" onSubmit={(event: FormEvent) => { event.preventDefault(); void submit(); }}>
      <SelectField label="假別" value={leaveTypeId} onChange={setLeaveTypeId} options={options} allowEmpty="請選擇" required error={fieldErrors.leaveTypeId} />
      <TextField label="年度開始日" type="date" required value={periodStart} onChange={setPeriodStart} error={fieldErrors.periodStart} />
      <TextField label="時數" type="number" required value={hours} onChange={setHours} error={fieldErrors.hours} />
      <TextArea label="原因" value={reason} onChange={setReason} error={fieldErrors.reason} />
      <FormError error={error} />
      <div className="formActions">
        <button className="primary" type="submit" disabled={pending}>儲存</button>
        <button className="secondary" type="button" onClick={onDone}>取消</button>
      </div>
    </form>
  );
}
