import { useState } from "react";
import type { AuditEntry } from "../../api/types";
import { usePermissions } from "../../auth/usePermissions";
import { SelectField } from "../../forms/fields";
import { formatDay, formatTime } from "../../forms/time";
import { DataTable, type Column } from "../../shell/DataTable";
import { DetailList } from "../../shell/DetailList";
import { Drawer } from "../../shell/Drawer";
import { PageHead } from "../../shell/PageHead";
import { useDrawerParams } from "../../shell/useDrawerParams";
import { useAudit, useUsers } from "./queries";

const moduleOptions = ["org", "core", "booking"].map((value) => ({ value, label: value }));
const json = (value: unknown) => (value === null || value === undefined ? "—" : JSON.stringify(value, null, 2));

export function AuditPage() {
  const { can } = usePermissions();
  const [module, setModule] = useState("");
  const { data, hasNextPage, fetchNextPage, isFetchingNextPage } = useAudit(module);
  const { data: users } = useUsers(can("core.users.manage"));
  const drawer = useDrawerParams();
  const entries = (data?.pages ?? []).flat();
  const selected = entries.find((item) => String(item.id) === drawer.selectedId) ?? null;
  const who = (id: number | null) => (id === null ? "系統" : users?.find((item) => item.id === id)?.email ?? `#${id}`);

  const columns: Column<AuditEntry>[] = [
    { label: "時間", render: (row) => `${formatDay(row.at)} ${formatTime(row.at)}`, text: (row) => row.at },
    { label: "使用者", render: (row) => who(row.userId), text: (row) => who(row.userId) },
    { label: "模組", render: (row) => row.module, text: (row) => row.module },
    { label: "動作", render: (row) => row.action, text: (row) => row.action },
    { label: "對象", render: (row) => `${row.entity} #${row.entityId}`, text: (row) => `${row.entity} ${row.entityId}` },
  ];

  return (
    <div className="inner">
      <PageHead headline="Audit log" />
      <div className="weekBar">
        <SelectField label="模組" value={module} onChange={setModule} options={moduleOptions} allowEmpty="全部" />
      </div>
      <DataTable
        columns={columns} rows={entries} rowKey={(row) => String(row.id)} selectedKey={drawer.selectedId}
        onSelect={(row) => drawer.openView(String(row.id))} filterPlaceholder="篩選稽核紀錄…"
      />
      {hasNextPage && (
        <p><button className="secondary" type="button" disabled={isFetchingNextPage} onClick={() => { void fetchNextPage(); }}>載入更多</button></p>
      )}
      <Drawer open={drawer.mode === "view" && selected !== null} title={selected ? `${selected.action} #${selected.entityId}` : ""} onClose={drawer.close}>
        {selected && (
          <DetailList
            items={[
              ["時間", `${formatDay(selected.at)} ${formatTime(selected.at)}`], ["使用者", who(selected.userId)],
              ["模組", selected.module], ["動作", selected.action],
              ["修改前", <pre key="b" className="mono">{json(selected.before)}</pre>],
              ["修改後", <pre key="a" className="mono">{json(selected.after)}</pre>],
            ]}
          />
        )}
      </Drawer>
    </div>
  );
}
