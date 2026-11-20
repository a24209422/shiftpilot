import { useEffect, useState } from "react";
import { apiSend } from "../../api/client";
import type { Resource } from "../../api/types";
import { usePermissions } from "../../auth/usePermissions";
import { CheckboxField } from "../../forms/fields";
import { FormError } from "../../forms/FormError";
import { useSubmit } from "../../forms/useSubmit";
import { DataTable, type Column } from "../../shell/DataTable";
import { DetailList } from "../../shell/DetailList";
import { Drawer } from "../../shell/Drawer";
import { Icon } from "../../shell/icons";
import { PageHead } from "../../shell/PageHead";
import { useToast } from "../../shell/Toast";
import { useDrawerParams } from "../../shell/useDrawerParams";
import { resourceKindLabels, resourceKindTones } from "./labels";
import { ResourceForm } from "./ResourceForm";
import { useResources } from "./queries";

function StatusTag({ resource }: { resource: Resource }) {
  return resource.isActive ? <span className="tag ok">啟用</span> : <span className="tag mute">已停用</span>;
}

const columns: Column<Resource>[] = [
  { label: "名稱", render: (row) => row.name, text: (row) => row.name },
  {
    label: "種類",
    render: (row) => <span className={`tag ${resourceKindTones[row.kind]}`}>{resourceKindLabels[row.kind]}</span>,
    text: (row) => resourceKindLabels[row.kind],
  },
  { label: "地點", render: (row) => row.location ?? "—", text: (row) => row.location ?? "" },
  { label: "容量", render: (row) => row.capacity ?? "—", text: (row) => String(row.capacity ?? "") },
  { label: "狀態", render: (row) => <StatusTag resource={row} />, text: (row) => (row.isActive ? "啟用" : "已停用") },
];

function ResourceActions({ resource, onEdit }: { resource: Resource; onEdit(): void }) {
  const toast = useToast();
  const toggle = useSubmit(
    () => apiSend("PATCH", `/api/booking/resources/${resource.id}`, { isActive: !resource.isActive }),
    { onSuccess: () => toast(resource.isActive ? "已停用資源" : "已重新啟用資源"), invalidate: [["resources"], ["summary"]] },
  );
  return (
    <>
      <FormError error={toggle.error} />
      <button className="primary" type="button" onClick={onEdit}>編輯</button>
      <button className="danger" type="button" disabled={toggle.pending} onClick={() => { void toggle.submit(); }}>
        {resource.isActive ? "停用" : "重新啟用"}
      </button>
    </>
  );
}

export function ResourcesPage() {
  const { can } = usePermissions();
  const canManage = can("booking.resources.manage");
  const [includeInactive, setIncludeInactive] = useState(false);
  const { data, isSuccess } = useResources(includeInactive);
  const drawer = useDrawerParams();
  const resources = data ?? [];
  const selected = resources.find((item) => String(item.id) === drawer.selectedId) ?? null;

  // 停用後在「不含已停用」的列表裡消失時，不能留著顯示舊資料的面板
  useEffect(() => {
    if (isSuccess && (drawer.mode === "view" || drawer.mode === "edit") && !selected) drawer.close();
  }, [isSuccess, drawer.mode, selected]); // eslint-disable-line react-hooks/exhaustive-deps

  const title = drawer.mode === "new" ? "新增資源" : selected?.name ?? "";
  const open = drawer.mode === "new" || (drawer.mode !== null && selected !== null);

  return (
    <div className="inner">
      <PageHead
        headline="Resources"
        action={canManage && <button className="primary" type="button" onClick={drawer.openNew}><Icon name="plus" size={16} />新增資源</button>}
      />
      <div className="checkRow"><CheckboxField label="含已停用" checked={includeInactive} onChange={setIncludeInactive} /></div>
      <DataTable
        columns={columns} rows={resources} rowKey={(row) => String(row.id)} selectedKey={drawer.selectedId}
        onSelect={(row) => drawer.openView(String(row.id))} filterPlaceholder="篩選資源…"
      />
      <Drawer
        open={open} title={title} onClose={drawer.close}
        footer={canManage && drawer.mode === "view" && selected ? <ResourceActions key={selected.id} resource={selected} onEdit={() => drawer.openEdit(String(selected.id))} /> : undefined}
      >
        {drawer.mode === "new" && <ResourceForm onDone={drawer.close} />}
        {drawer.mode === "edit" && selected && <ResourceForm key={selected.id} resource={selected} onDone={() => drawer.openView(String(selected.id))} />}
        {drawer.mode === "view" && selected && (
          <DetailList
            items={[
              ["名稱", selected.name],
              ["種類", resourceKindLabels[selected.kind]],
              ["地點", selected.location ?? "—"],
              ["容量", selected.capacity ?? "—"],
              ["設備特色", selected.features.length ? selected.features.join("、") : "—"],
              ["備註", selected.note ?? "—"],
              ["狀態", <StatusTag key="s" resource={selected} />],
            ]}
          />
        )}
      </Drawer>
    </div>
  );
}
