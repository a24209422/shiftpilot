import { useState, type FormEvent } from "react";
import { apiSend } from "../../api/client";
import type { Role, User } from "../../api/types";
import { roleLabels } from "../../auth/roles";
import { CheckboxField, SelectField, TextField } from "../../forms/fields";
import { FormError } from "../../forms/FormError";
import { useSubmit } from "../../forms/useSubmit";
import { useToast } from "../../shell/Toast";
import { useEmployees } from "../org/queries";
import { useUsers } from "./queries";

const roleOptions = (Object.keys(roleLabels) as Role[]).map((value) => ({ value, label: roleLabels[value] }));

export function UserForm({ user, onDone }: { user?: User; onDone(): void }) {
  const toast = useToast();
  const { data: employeeData } = useEmployees();
  const { data: userData } = useUsers();
  const [email, setEmail] = useState(user?.email ?? "");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<string>(user?.role ?? "employee");
  const [employeeId, setEmployeeId] = useState(user?.employeeId?.toString() ?? "");
  const [isActive, setIsActive] = useState(user?.isActive ?? true);
  const [passwordError, setPasswordError] = useState<string | null>(null);

  // 一個員工只能連一個帳號：列出還沒被連走的在職員工（編輯時加上自己目前連的那位）
  const linked = new Set((userData ?? []).map((item) => item.employeeId).filter((id): id is number => id !== null));
  const employeeOptions = (employeeData ?? [])
    .filter((item) => !linked.has(item.id) || item.id === user?.employeeId)
    .map((item) => ({ value: String(item.id), label: item.name }));

  const { submit, pending, error, fieldErrors } = useSubmit(
    () => {
      const linkedId = employeeId === "" ? null : Number(employeeId);
      if (!user) return apiSend("POST", "/api/core/users", { email, password, role, employeeId: linkedId });
      const changed: Record<string, unknown> = {};
      if (role !== user.role) changed.role = role;
      if (linkedId !== user.employeeId) changed.employeeId = linkedId;
      if (isActive !== user.isActive) changed.isActive = isActive;
      if (Object.keys(changed).length === 0) return Promise.resolve(undefined);
      return apiSend("PATCH", `/api/core/users/${user.id}`, changed);
    },
    { onSuccess: () => { toast(user ? "已更新帳號" : "已建立帳號"); onDone(); }, invalidate: [["users"]] },
  );

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!user && (password.length < 8 || password.length > 128)) {
      setPasswordError("密碼要 8 到 128 字元");
      return;
    }
    setPasswordError(null);
    void submit();
  }

  return (
    <form className="form" onSubmit={onSubmit}>
      <TextField label="Email" type="email" required value={email} onChange={setEmail} disabled={Boolean(user)} error={fieldErrors.email} />
      {!user && <TextField label="密碼" type="password" required value={password} onChange={setPassword} error={passwordError ?? fieldErrors.password} />}
      <SelectField label="角色" value={role} onChange={setRole} options={roleOptions} error={fieldErrors.role} />
      <SelectField label="連結員工" value={employeeId} onChange={setEmployeeId} options={employeeOptions} allowEmpty="（不連結）" error={fieldErrors.employeeId} />
      {user && <CheckboxField label="啟用中（取消勾選就是停用帳號）" checked={isActive} onChange={setIsActive} />}
      <FormError error={error} />
      <div className="formActions">
        <button className="primary" type="submit" disabled={pending}>儲存</button>
        <button className="secondary" type="button" onClick={onDone}>取消</button>
      </div>
    </form>
  );
}
