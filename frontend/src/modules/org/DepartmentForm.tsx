import { useState, type FormEvent } from "react";
import { apiSend } from "../../api/client";
import type { Department } from "../../api/types";
import { SelectField, TextField } from "../../forms/fields";
import { FormError } from "../../forms/FormError";
import { useSubmit } from "../../forms/useSubmit";
import { useToast } from "../../shell/Toast";

export function DepartmentForm({ department, departments, onDone }: { department?: Department; departments: Department[]; onDone(): void }) {
  const toast = useToast();
  const [name, setName] = useState(department?.name ?? "");
  const [parentId, setParentId] = useState(department?.parentId?.toString() ?? "");
  const options = departments.filter((item) => item.id !== department?.id).map((item) => ({ value: String(item.id), label: item.name }));

  const { submit, pending, error, fieldErrors } = useSubmit(
    async () => {
      const values = { name, parentId: parentId === "" ? null : Number(parentId) };
      if (!department) return apiSend("POST", "/api/org/departments", values);
      const changed: Record<string, unknown> = {};
      if (values.name !== department.name) changed.name = values.name;
      if (values.parentId !== department.parentId) changed.parentId = values.parentId;
      if (Object.keys(changed).length === 0) return undefined;
      return apiSend("PATCH", `/api/org/departments/${department.id}`, changed);
    },
    { onSuccess: () => { toast(department ? "已更新部門" : "已新增部門"); onDone(); }, invalidate: [["departments"], ["employees"]] },
  );

  return (
    <form className="form" onSubmit={(event: FormEvent) => { event.preventDefault(); void submit(); }}>
      <TextField label="名稱" required value={name} onChange={setName} error={fieldErrors.name} />
      <SelectField label="上層部門" value={parentId} onChange={setParentId} options={options} allowEmpty="（無）" error={fieldErrors.parentId} />
      <FormError error={error} />
      <div className="formActions">
        <button className="primary" type="submit" disabled={pending}>儲存</button>
        <button className="secondary" type="button" onClick={onDone}>取消</button>
      </div>
    </form>
  );
}
