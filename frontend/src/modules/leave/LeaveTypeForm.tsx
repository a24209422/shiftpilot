import { useState, type FormEvent } from "react";
import { apiSend } from "../../api/client";
import type { LeaveType, QuotaKind } from "../../api/types";
import { SelectField, TextField } from "../../forms/fields";
import { FormError } from "../../forms/FormError";
import { useSubmit } from "../../forms/useSubmit";
import { useToast } from "../../shell/Toast";
import { quotaKindLabels } from "./labels";

const ratioOptions = [{ value: "1", label: "全薪" }, { value: "0.5", label: "半薪" }, { value: "0", label: "不支薪" }];
const kindOptions = (Object.keys(quotaKindLabels) as QuotaKind[]).map((value) => ({ value, label: quotaKindLabels[value] }));

export function LeaveTypeForm({ leaveType, onDone }: { leaveType?: LeaveType; onDone(): void }) {
  const toast = useToast();
  const [code, setCode] = useState(leaveType?.code ?? "");
  const [name, setName] = useState(leaveType?.name ?? "");
  const [paidRatio, setPaidRatio] = useState(String(leaveType?.paidRatio ?? 1));
  const [quotaKind, setQuotaKind] = useState<QuotaKind>(leaveType?.quotaKind ?? "yearly_cap");
  const [capHours, setCapHours] = useState(leaveType?.annualCapHours ? String(leaveType.annualCapHours) : "");
  const { submit, pending, error, fieldErrors } = useSubmit(
    () => {
      const annualCapHours = quotaKind === "yearly_cap" ? Number(capHours) : null;
      if (!leaveType) return apiSend("POST", "/api/leave/types", { code, name, paidRatio: Number(paidRatio), quotaKind, annualCapHours });
      // 額度類型與代碼建立後不能改，只送可以改的欄位
      const changed: Record<string, unknown> = {};
      if (name !== leaveType.name) changed.name = name;
      if (Number(paidRatio) !== leaveType.paidRatio) changed.paidRatio = Number(paidRatio);
      if (quotaKind === "yearly_cap" && annualCapHours !== leaveType.annualCapHours) changed.annualCapHours = annualCapHours;
      if (Object.keys(changed).length === 0) return Promise.resolve(undefined);
      return apiSend("PATCH", `/api/leave/types/${leaveType.id}`, changed);
    },
    { onSuccess: () => { toast(leaveType ? "已更新假別" : "已新增假別"); onDone(); }, invalidate: [["leave"]] },
  );
  return (
    <form className="form" onSubmit={(event: FormEvent) => { event.preventDefault(); void submit(); }}>
      {!leaveType && <TextField label="代碼" required value={code} onChange={setCode} error={fieldErrors.code} />}
      <TextField label="名稱" required value={name} onChange={setName} error={fieldErrors.name} />
      <SelectField label="支薪比例" value={paidRatio} onChange={setPaidRatio} options={ratioOptions} />
      {leaveType
        ? <div className="formNote">額度類型：{quotaKindLabels[leaveType.quotaKind]}（建立後不能修改）</div>
        : <SelectField label="額度類型" value={quotaKind} onChange={(value) => setQuotaKind(value as QuotaKind)} options={kindOptions} error={fieldErrors.quotaKind} />}
      {quotaKind === "yearly_cap" && <TextField label="年度上限（小時）" type="number" required value={capHours} onChange={setCapHours} error={fieldErrors.annualCapHours} />}
      <FormError error={error} />
      <div className="formActions">
        <button className="primary" type="submit" disabled={pending}>儲存</button>
        <button className="secondary" type="button" onClick={onDone}>取消</button>
      </div>
    </form>
  );
}
