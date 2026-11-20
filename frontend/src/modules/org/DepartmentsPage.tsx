import { useEffect } from "react";
import type { Department } from "../../api/types";
import { usePermissions } from "../../auth/usePermissions";
import { DataTable, type Column } from "../../shell/DataTable";
import { DetailList } from "../../shell/DetailList";
import { Drawer } from "../../shell/Drawer";
import { Icon } from "../../shell/icons";
import { PageHead } from "../../shell/PageHead";
import { useDrawerParams } from "../../shell/useDrawerParams";
import { DepartmentForm } from "./DepartmentForm";
import { useDepartments, useEmployees } from "./queries";

export function DepartmentsPage() {
  const { can } = usePermissions();
  const canManage = can("org.manage");
  const { data, isSuccess } = useDepartments();
  const { data: employees } = useEmployees();
  const drawer = useDrawerParams();
  const departments = data ?? [];
  const selected = departments.find((item) => String(item.id) === drawer.selectedId) ?? null;
  const nameOf = (id: number | null) => departments.find((item) => item.id === id)?.name ?? "—";
  const countOf = (id: number) => (employees ?? []).filter((item) => item.departmentId === id).length;

  useEffect(() => {
    if (isSuccess && (drawer.mode === "view" || drawer.mode === "edit") && !selected) drawer.close();
  }, [isSuccess, drawer.mode, selected]); // eslint-disable-line react-hooks/exhaustive-deps

  const columns: Column<Department>[] = [
    { label: "名稱", render: (row) => row.name, text: (row) => row.name },
    { label: "上層部門", render: (row) => nameOf(row.parentId), text: (row) => nameOf(row.parentId) },
    { label: "員工數", render: (row) => countOf(row.id), text: (row) => String(countOf(row.id)) },
  ];
  const open = drawer.mode === "new" || (drawer.mode !== null && selected !== null);

  return (
    <div className="inner">
      <PageHead
        headline="Departments"
        action={canManage && <button className="primary" type="button" onClick={drawer.openNew}><Icon name="plus" size={16} />新增部門</button>}
      />
      <DataTable
        columns={columns} rows={departments} rowKey={(row) => String(row.id)} selectedKey={drawer.selectedId}
        onSelect={(row) => drawer.openView(String(row.id))} filterPlaceholder="篩選部門…"
      />
      <Drawer
        open={open} title={drawer.mode === "new" ? "新增部門" : selected?.name ?? ""} onClose={drawer.close}
        footer={canManage && drawer.mode === "view" && selected
          ? <button className="primary" type="button" onClick={() => drawer.openEdit(String(selected.id))}>編輯</button> : undefined}
      >
        {drawer.mode === "new" && <DepartmentForm departments={departments} onDone={drawer.close} />}
        {drawer.mode === "edit" && selected && (
          <DepartmentForm key={selected.id} department={selected} departments={departments} onDone={() => drawer.openView(String(selected.id))} />
        )}
        {drawer.mode === "view" && selected && (
          <DetailList items={[["名稱", selected.name], ["上層部門", nameOf(selected.parentId)], ["員工數", countOf(selected.id)]]} />
        )}
      </Drawer>
    </div>
  );
}
