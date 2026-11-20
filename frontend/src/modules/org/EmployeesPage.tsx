import { useEffect, useState } from "react";
import { apiSend } from "../../api/client";
import type { Employee } from "../../api/types";
import { usePermissions } from "../../auth/usePermissions";
import { CheckboxField, TextField } from "../../forms/fields";
import { FormError } from "../../forms/FormError";
import { toLocalDate } from "../../forms/time";
import { useSubmit } from "../../forms/useSubmit";
import { DataTable, type Column } from "../../shell/DataTable";
import { DetailList } from "../../shell/DetailList";
import { Drawer } from "../../shell/Drawer";
import { Icon } from "../../shell/icons";
import { PageHead } from "../../shell/PageHead";
import { useToast } from "../../shell/Toast";
import { useDrawerParams } from "../../shell/useDrawerParams";
import { EmployeeForm } from "./EmployeeForm";
import { useDepartments, useEmployees } from "./queries";

const statusText = (employee: Employee) => (employee.isActive ? "在職" : employee.leftOn ? "已離職" : "已停用");
const StatusTag = ({ employee }: { employee: Employee }) => <span className={`tag ${employee.isActive ? "ok" : "mute"}`}>{statusText(employee)}</span>;

function EmployeeActions({ employee, onEdit }: { employee: Employee; onEdit(): void }) {
  const toast = useToast();
  const [confirming, setConfirming] = useState(false);
  const [leftOn, setLeftOn] = useState(toLocalDate(new Date()));
  const change = useSubmit(
    () => apiSend("PATCH", `/api/org/employees/${employee.id}`, employee.isActive ? { isActive: false, leftOn: leftOn || null } : { isActive: true, leftOn: null }),
    { onSuccess: () => { toast(employee.isActive ? "已停用員工" : "已重新啟用員工"); setConfirming(false); }, invalidate: [["employees"]] },
  );
  if (confirming) {
    return (
      <div className="form" style={{ width: "100%" }}>
        <TextField label="離職日" type="date" value={leftOn} onChange={setLeftOn} />
        <FormError error={change.error} />
        <div className="formActions">
          <button className="danger" type="button" disabled={change.pending} onClick={() => { void change.submit(); }}>確定停用</button>
          <button className="secondary" type="button" onClick={() => setConfirming(false)}>先不要</button>
        </div>
      </div>
    );
  }
  return (
    <>
      <FormError error={change.error} />
      <button className="primary" type="button" onClick={onEdit}>編輯</button>
      {employee.isActive
        ? <button className="danger" type="button" onClick={() => setConfirming(true)}>停用</button>
        : <button className="danger" type="button" disabled={change.pending} onClick={() => { void change.submit(); }}>重新啟用</button>}
    </>
  );
}

export function EmployeesPage() {
  const { can } = usePermissions();
  const canManage = can("org.manage");
  const [includeInactive, setIncludeInactive] = useState(false);
  const { data, isSuccess } = useEmployees(true);
  const { data: departmentData } = useDepartments();
  const drawer = useDrawerParams();
  const all = data ?? [];
  const departments = departmentData ?? [];
  const rows = includeInactive ? all : all.filter((item) => item.isActive);
  const selected = all.find((item) => String(item.id) === drawer.selectedId) ?? null;
  const departmentName = (id: number) => departments.find((item) => item.id === id)?.name ?? "—";
  const managerName = (id: number | null) => all.find((item) => item.id === id)?.name ?? "—";

  useEffect(() => {
    if (isSuccess && (drawer.mode === "view" || drawer.mode === "edit") && !selected) drawer.close();
  }, [isSuccess, drawer.mode, selected]); // eslint-disable-line react-hooks/exhaustive-deps

  const columns: Column<Employee>[] = [
    { label: "員工編號", render: (row) => row.employeeNo, text: (row) => row.employeeNo },
    { label: "姓名", render: (row) => row.name, text: (row) => row.name },
    { label: "部門", render: (row) => departmentName(row.departmentId), text: (row) => departmentName(row.departmentId) },
    { label: "職稱", render: (row) => row.jobTitle, text: (row) => row.jobTitle },
    { label: "主管", render: (row) => managerName(row.managerId), text: (row) => managerName(row.managerId) },
    { label: "到職日", render: (row) => row.hiredOn, text: (row) => row.hiredOn },
    { label: "狀態", render: (row) => <StatusTag employee={row} />, text: statusText },
  ];
  const open = drawer.mode === "new" || (drawer.mode !== null && selected !== null);

  return (
    <div className="inner">
      <PageHead
        headline="People."
        sub={`員工・共 ${rows.length} 筆。部門、職稱、主管與到職日`}
        action={canManage && <button className="primary" type="button" onClick={drawer.openNew}><Icon name="plus" size={16} />新增員工</button>}
      />
      <div className="checkRow"><CheckboxField label="含已停用" checked={includeInactive} onChange={setIncludeInactive} /></div>
      <DataTable
        columns={columns} rows={rows} rowKey={(row) => String(row.id)} selectedKey={drawer.selectedId}
        onSelect={(row) => drawer.openView(String(row.id))} filterPlaceholder="篩選員工…"
      />
      <Drawer
        open={open} title={drawer.mode === "new" ? "新增員工" : selected?.name ?? ""} onClose={drawer.close}
        footer={canManage && drawer.mode === "view" && selected ? <EmployeeActions key={selected.id} employee={selected} onEdit={() => drawer.openEdit(String(selected.id))} /> : undefined}
      >
        {drawer.mode === "new" && <EmployeeForm employees={all} departments={departments} onDone={drawer.close} />}
        {drawer.mode === "edit" && selected && (
          <EmployeeForm key={selected.id} employee={selected} employees={all} departments={departments} onDone={() => drawer.openView(String(selected.id))} />
        )}
        {drawer.mode === "view" && selected && (
          <DetailList
            items={[
              ["員工編號", selected.employeeNo], ["姓名", selected.name], ["Email", selected.email ?? "—"],
              ["部門", departmentName(selected.departmentId)], ["職稱", selected.jobTitle], ["主管", managerName(selected.managerId)],
              ["到職日", selected.hiredOn], ["離職日", selected.leftOn ?? "—"], ["狀態", <StatusTag key="s" employee={selected} />],
            ]}
          />
        )}
      </Drawer>
    </div>
  );
}
