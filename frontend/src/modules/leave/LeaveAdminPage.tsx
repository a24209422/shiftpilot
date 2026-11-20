import { useState } from "react";
import { useSearchParams } from "react-router";
import { apiSend } from "../../api/client";
import type { LeaveAdjustment, LeaveType } from "../../api/types";
import { SelectField } from "../../forms/fields";
import { FormError } from "../../forms/FormError";
import { useSubmit } from "../../forms/useSubmit";
import { DataTable, type Column } from "../../shell/DataTable";
import { DetailList } from "../../shell/DetailList";
import { Drawer } from "../../shell/Drawer";
import { Icon } from "../../shell/icons";
import { PageHead } from "../../shell/PageHead";
import { Tabs } from "../../shell/Tabs";
import { useToast } from "../../shell/Toast";
import { useDrawerParams } from "../../shell/useDrawerParams";
import { useEmployees } from "../org/queries";
import { AdjustmentForm } from "./AdjustmentForm";
import { quotaKindLabels } from "./labels";
import { LeaveTypeForm } from "./LeaveTypeForm";
import { useAdjustments, useLeaveTypes } from "./queries";
import { UnusedReport } from "./UnusedReport";

const tabs = [{ key: "types", label: "假別" }, { key: "adjustments", label: "額度調整" }, { key: "unused", label: "未休特休" }];
const quotaText = (row: LeaveType) => (row.quotaKind === "yearly_cap" ? `每年 ${row.annualCapHours} 小時` : quotaKindLabels[row.quotaKind]);
const typeColumns: Column<LeaveType>[] = [
  { label: "名稱", render: (row) => row.name, text: (row) => row.name },
  { label: "代碼", render: (row) => <span className="mono">{row.code}</span>, text: (row) => row.code },
  { label: "額度", render: quotaText, text: quotaText },
  { label: "支薪", render: (row) => `${row.paidRatio * 100}%`, text: (row) => String(row.paidRatio) },
  { label: "狀態", render: (row) => (row.isActive ? <span className="tag ok">啟用</span> : <span className="tag mute">停用</span>), text: (row) => (row.isActive ? "啟用" : "停用") },
];
const adjustmentColumns: Column<LeaveAdjustment>[] = [
  { label: "假別", render: (row) => row.leaveTypeName, text: (row) => row.leaveTypeName },
  { label: "年度開始", render: (row) => row.periodStart, text: (row) => row.periodStart },
  { label: "時數", render: (row) => `${row.hours > 0 ? "+" : ""}${row.hours} 小時`, text: (row) => String(row.hours) },
  { label: "原因", render: (row) => row.reason, text: (row) => row.reason },
  { label: "建立者", render: (row) => row.createdByEmail, text: (row) => row.createdByEmail },
];

function ToggleActive({ leaveType, onDone }: { leaveType: LeaveType; onDone(): void }) {
  const toast = useToast();
  const toggle = useSubmit(
    () => apiSend("PATCH", `/api/leave/types/${leaveType.id}`, { isActive: !leaveType.isActive }),
    { onSuccess: () => { toast(leaveType.isActive ? "已停用" : "已啟用"); onDone(); }, invalidate: [["leave"]] },
  );
  return (
    <>
      <FormError error={toggle.error} />
      <button className={leaveType.isActive ? "danger" : "secondary"} type="button" disabled={toggle.pending} onClick={() => void toggle.submit()}>
        {leaveType.isActive ? "停用" : "啟用"}
      </button>
    </>
  );
}

export function LeaveAdminPage() {
  const [params, setParams] = useSearchParams();
  const drawer = useDrawerParams();
  const tab = tabs.some((item) => item.key === params.get("tab")) ? params.get("tab")! : "types";
  const setTab = (key: string) => setParams({ tab: key });
  const { data: types } = useLeaveTypes(true);
  const { data: employees } = useEmployees();
  const [employeeId, setEmployeeId] = useState("");
  const adjustments = useAdjustments(employeeId ? Number(employeeId) : null);
  const selectedType = (types ?? []).find((item) => String(item.id) === drawer.selectedId) ?? null;

  const action = tab === "types"
    ? <button className="primary" type="button" onClick={drawer.openNew}><Icon name="plus" size={16} />新增假別</button>
    : tab === "adjustments"
      ? <button className="primary" type="button" disabled={!employeeId} onClick={drawer.openNew}><Icon name="plus" size={16} />新增調整</button>
      : null;
  const drawerTitle = tab === "adjustments" ? "新增額度調整" : drawer.mode === "new" ? "新增假別" : selectedType?.name ?? "";
  const open = drawer.mode === "new" || (tab === "types" && drawer.mode !== null && selectedType !== null);

  return (
    <div className="inner">
      <PageHead headline="Leave rules" action={action} />
      <Tabs tabs={tabs} value={tab} onChange={setTab} />
      {tab === "types" && (
        <DataTable columns={typeColumns} rows={types ?? []} rowKey={(row) => String(row.id)} selectedKey={drawer.selectedId}
          onSelect={(row) => drawer.openView(String(row.id))} filterPlaceholder="篩選假別…" emptyText="還沒有假別" />
      )}
      {tab === "adjustments" && (
        <>
          <SelectField label="員工" value={employeeId} onChange={setEmployeeId} allowEmpty="請選擇"
            options={(employees ?? []).map((item) => ({ value: String(item.id), label: `${item.name}（${item.employeeNo}）` }))} />
          {employeeId && <DataTable columns={adjustmentColumns} rows={adjustments.data ?? []} rowKey={(row) => String(row.id)}
            selectedKey={null} onSelect={() => {}} filterPlaceholder="篩選調整…" emptyText="這位員工沒有額度調整" />}
        </>
      )}
      {tab === "unused" && <UnusedReport />}
      <Drawer
        open={open} title={drawerTitle} onClose={drawer.close}
        footer={tab === "types" && drawer.mode === "view" && selectedType ? (
          <>
            <button className="primary" type="button" onClick={() => drawer.openEdit(String(selectedType.id))}>編輯</button>
            <ToggleActive key={selectedType.id} leaveType={selectedType} onDone={drawer.close} />
          </>
        ) : undefined}
      >
        {tab === "types" && drawer.mode === "new" && <LeaveTypeForm onDone={drawer.close} />}
        {tab === "types" && drawer.mode === "edit" && selectedType && <LeaveTypeForm key={selectedType.id} leaveType={selectedType} onDone={() => drawer.openView(String(selectedType.id))} />}
        {tab === "types" && drawer.mode === "view" && selectedType && (
          <DetailList items={[["名稱", selectedType.name], ["代碼", selectedType.code], ["額度", quotaText(selectedType)], ["支薪", `${selectedType.paidRatio * 100}%`]]} />
        )}
        {tab === "adjustments" && drawer.mode === "new" && employeeId && <AdjustmentForm employeeId={Number(employeeId)} onDone={drawer.close} />}
      </Drawer>
    </div>
  );
}
