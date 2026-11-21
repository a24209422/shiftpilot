import { apiSend } from "../../api/client";
import type { ShiftType } from "../../api/types";
import { FormError } from "../../forms/FormError";
import { useSubmit } from "../../forms/useSubmit";
import { DataTable, type Column } from "../../shell/DataTable";
import { DetailList } from "../../shell/DetailList";
import { Drawer } from "../../shell/Drawer";
import { Icon } from "../../shell/icons";
import { PageHead } from "../../shell/PageHead";
import { useToast } from "../../shell/Toast";
import { useDrawerParams } from "../../shell/useDrawerParams";
import { shiftHours } from "./format";
import { useShiftTypes } from "./queries";
import { ShiftTypeForm } from "./ShiftTypeForm";

const breakText = (row: ShiftType) => (row.breakStart ? `${row.breakStart}–${row.breakEnd}` : "—");
const columns: Column<ShiftType>[] = [
  { label: "名稱", render: (row) => row.name, text: (row) => row.name },
  { label: "代碼", render: (row) => <span className="mono">{row.code}</span>, text: (row) => row.code },
  { label: "時間", render: (row) => shiftHours(row), text: (row) => shiftHours(row) },
  { label: "休息", render: breakText, text: breakText },
  { label: "預設", render: (row) => (row.isDefault ? <span className="tag ok">預設</span> : "—"), text: (row) => (row.isDefault ? "預設" : "") },
  { label: "狀態", render: (row) => (row.isActive ? <span className="tag ok">啟用</span> : <span className="tag mute">停用</span>), text: (row) => (row.isActive ? "啟用" : "停用") },
];

function usePatchType(shiftType: ShiftType, body: Record<string, boolean>, message: string, onDone: () => void) {
  const toast = useToast();
  return useSubmit(
    () => apiSend("PATCH", `/api/shift/types/${shiftType.id}`, body),
    { onSuccess: () => { toast(message); onDone(); }, invalidate: [["shifts"]] },
  );
}

function TypeActions({ shiftType, onEdit, onDone }: { shiftType: ShiftType; onEdit(): void; onDone(): void }) {
  const makeDefault = usePatchType(shiftType, { isDefault: true }, "已設為預設班", onDone);
  const deactivate = usePatchType(shiftType, { isActive: false }, "已停用", onDone);
  const activate = usePatchType(shiftType, { isActive: true }, "已啟用", onDone);
  const pending = makeDefault.pending || deactivate.pending || activate.pending;
  return (
    <>
      <FormError error={makeDefault.error ?? deactivate.error ?? activate.error} />
      <button className="primary" type="button" onClick={onEdit}>編輯</button>
      {!shiftType.isDefault && shiftType.isActive && (
        <button className="secondary" type="button" disabled={pending} onClick={() => void makeDefault.submit()}>設為預設</button>
      )}
      {shiftType.isActive ? (
        // 預設班停用等於所有沒排班的人都變成休息，後端也會擋
        <button className="danger" type="button" disabled={pending || shiftType.isDefault} onClick={() => void deactivate.submit()}>停用</button>
      ) : (
        <button className="secondary" type="button" disabled={pending} onClick={() => void activate.submit()}>啟用</button>
      )}
    </>
  );
}

export function ShiftTypesPage() {
  const drawer = useDrawerParams();
  const { data } = useShiftTypes(true);
  const types = data ?? [];
  const selected = types.find((item) => String(item.id) === drawer.selectedId) ?? null;
  const open = drawer.mode === "new" || (drawer.mode !== null && selected !== null);
  return (
    <div className="inner">
      <PageHead headline="Shift types" action={<button className="primary" type="button" onClick={drawer.openNew}><Icon name="plus" size={16} />新增班別</button>} />
      {data && !types.some((item) => item.isDefault) && <div className="formWarn" role="alert">目前沒有預設班：沒排班的人會被當作休息</div>}
      <DataTable columns={columns} rows={types} rowKey={(row) => String(row.id)} selectedKey={drawer.selectedId}
        onSelect={(row) => drawer.openView(String(row.id))} filterPlaceholder="篩選班別…" emptyText="還沒有班別" />
      <Drawer
        open={open} title={drawer.mode === "new" ? "新增班別" : selected?.name ?? ""} onClose={drawer.close}
        footer={drawer.mode === "view" && selected
          ? <TypeActions key={selected.id} shiftType={selected} onEdit={() => drawer.openEdit(String(selected.id))} onDone={drawer.close} /> : undefined}
      >
        {drawer.mode === "new" && <ShiftTypeForm onDone={drawer.close} />}
        {drawer.mode === "edit" && selected && <ShiftTypeForm key={selected.id} shiftType={selected} onDone={() => drawer.openView(String(selected.id))} />}
        {drawer.mode === "view" && selected && (
          <DetailList items={[["名稱", selected.name], ["代碼", selected.code], ["時間", shiftHours(selected)], ["休息", breakText(selected)], ["預設", selected.isDefault ? "是" : "否"]]} />
        )}
      </Drawer>
    </div>
  );
}
