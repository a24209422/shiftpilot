import { useState, type FormEvent } from "react";
import { apiSend } from "../../api/client";
import type { Department, Employee } from "../../api/types";
import { SelectField, TextField } from "../../forms/fields";
import { FormError } from "../../forms/FormError";
import { useSubmit } from "../../forms/useSubmit";
import { useToast } from "../../shell/Toast";

interface Props { employee?: Employee; employees: Employee[]; departments: Department[]; onDone(): void }

export function EmployeeForm({ employee, employees, departments, onDone }: Props) {
  const toast = useToast();
  const [employeeNo, setEmployeeNo] = useState(employee?.employeeNo ?? "");
  const [name, setName] = useState(employee?.name ?? "");
  const [email, setEmail] = useState(employee?.email ?? "");
  const [departmentId, setDepartmentId] = useState(employee?.departmentId.toString() ?? "");
  const [jobTitle, setJobTitle] = useState(employee?.jobTitle ?? "");
  const [managerId, setManagerId] = useState(employee?.managerId?.toString() ?? "");
  const [hiredOn, setHiredOn] = useState(employee?.hiredOn ?? "");

  const departmentOptions = departments.map((item) => ({ value: String(item.id), label: item.name }));
  // 主管只能選在職的人，也不能是自己
  const managerOptions = employees
    .filter((item) => item.isActive && item.id !== employee?.id)
    .map((item) => ({ value: String(item.id), label: item.name }));

  const { submit, pending, error, fieldErrors } = useSubmit(
    async () => {
      const values = {
        employeeNo, name, email: email || null, departmentId: Number(departmentId), jobTitle,
        managerId: managerId === "" ? null : Number(managerId), hiredOn,
      };
      if (!employee) return apiSend("POST", "/api/org/employees", values);
      const changed: Record<string, unknown> = {};
      (Object.keys(values) as (keyof typeof values)[]).forEach((key) => {
        if (values[key] !== employee[key]) changed[key] = values[key];
      });
      if (Object.keys(changed).length === 0) return undefined;
      return apiSend("PATCH", `/api/org/employees/${employee.id}`, changed);
    },
    { onSuccess: () => { toast(employee ? "已更新員工" : "已新增員工"); onDone(); }, invalidate: [["employees"], ["departments"]] },
  );

  return (
    <form className="form" onSubmit={(event: FormEvent) => { event.preventDefault(); void submit(); }}>
      <TextField label="員工編號" required value={employeeNo} onChange={setEmployeeNo} error={fieldErrors.employeeNo} />
      <TextField label="姓名" required value={name} onChange={setName} error={fieldErrors.name} />
      <TextField label="Email" type="email" value={email} onChange={setEmail} error={fieldErrors.email} />
      <SelectField label="部門" required value={departmentId} onChange={setDepartmentId} options={departmentOptions} allowEmpty="請選擇" error={fieldErrors.departmentId} />
      <TextField label="職稱" required value={jobTitle} onChange={setJobTitle} error={fieldErrors.jobTitle} />
      <SelectField label="主管" value={managerId} onChange={setManagerId} options={managerOptions} allowEmpty="（無）" error={fieldErrors.managerId} />
      <TextField label="到職日" type="date" required value={hiredOn} onChange={setHiredOn} error={fieldErrors.hiredOn} />
      <FormError error={error} />
      <div className="formActions">
        <button className="primary" type="submit" disabled={pending}>儲存</button>
        <button className="secondary" type="button" onClick={onDone}>取消</button>
      </div>
    </form>
  );
}
