import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { apiGet, apiSend } from "../../api/client";
import type { CalendarDay } from "../../api/types";
import { usePermissions } from "../../auth/usePermissions";
import { FormError } from "../../forms/FormError";
import { formatDay } from "../../forms/time";
import { useSubmit } from "../../forms/useSubmit";
import { DataTable, type Column } from "../../shell/DataTable";
import { DetailList } from "../../shell/DetailList";
import { Drawer } from "../../shell/Drawer";
import { Icon } from "../../shell/icons";
import { PageHead } from "../../shell/PageHead";
import { useToast } from "../../shell/Toast";
import { useDrawerParams } from "../../shell/useDrawerParams";
import { CalendarDayForm, calendarKindLabels } from "./CalendarDayForm";

const fullDay = (day: string) => `${day.slice(0, 4)}/${formatDay(day)}`;
const KindTag = ({ day }: { day: CalendarDay }) => <span className={`tag ${day.kind === "holiday" ? "ok" : "warn"}`}>{calendarKindLabels[day.kind]}</span>;

const columns: Column<CalendarDay>[] = [
  { label: "日期", render: (row) => fullDay(row.day), text: (row) => row.day },
  { label: "種類", render: (row) => <KindTag day={row} />, text: (row) => calendarKindLabels[row.kind] },
  { label: "名稱", render: (row) => row.name, text: (row) => row.name },
];

function DayActions({ day, onEdit, onDeleted }: { day: CalendarDay; onEdit(): void; onDeleted(): void }) {
  const toast = useToast();
  const [confirming, setConfirming] = useState(false);
  const remove = useSubmit(
    () => apiSend("DELETE", `/api/org/calendarDays/${day.day}`),
    { onSuccess: () => { toast("已刪除日期"); onDeleted(); }, invalidate: [["calendarDays"]] },
  );
  return (
    <>
      <FormError error={remove.error} />
      <button className="primary" type="button" onClick={onEdit}>編輯</button>
      {/* 不用 window.confirm：瀏覽器的對話框會擋住自動化與測試 */}
      <button className="danger" type="button" disabled={remove.pending} onClick={(event) => {
        // 連點的第二下（detail > 1）不能直接當成「確定」，不然二次確認形同虛設
        if (event.detail > 1) return;
        if (confirming) void remove.submit(); else setConfirming(true);
      }}>
        {confirming ? "確定刪除？" : "刪除"}
      </button>
    </>
  );
}

export function CalendarPage() {
  const { can } = usePermissions();
  const canManage = can("org.manage");
  const [year, setYear] = useState(() => new Date().getFullYear());
  const { data, isSuccess } = useQuery({
    queryKey: ["calendarDays", year],
    queryFn: () => apiGet<CalendarDay[]>("/api/org/calendarDays", { from: `${year}-01-01`, to: `${year}-12-31` }),
  });
  const drawer = useDrawerParams();
  const days = data ?? [];
  const selected = days.find((item) => item.day === drawer.selectedId) ?? null;

  useEffect(() => {
    if (isSuccess && (drawer.mode === "view" || drawer.mode === "edit") && !selected) drawer.close();
  }, [isSuccess, drawer.mode, selected]); // eslint-disable-line react-hooks/exhaustive-deps

  const open = drawer.mode === "new" || (drawer.mode !== null && selected !== null);

  return (
    <div className="inner">
      <PageHead
        headline="Calendar."
        sub={`行事曆・${year} 年共 ${days.length} 筆。假日與補班日`}
        action={canManage && <button className="primary" type="button" onClick={drawer.openNew}><Icon name="plus" size={16} />新增日期</button>}
      />
      <div className="weekBar">
        <button className="secondary" type="button" onClick={() => setYear(year - 1)}>上一年</button>
        <button className="secondary" type="button" onClick={() => setYear(new Date().getFullYear())}>今年</button>
        <button className="secondary" type="button" onClick={() => setYear(year + 1)}>下一年</button>
      </div>
      <DataTable
        columns={columns} rows={days} rowKey={(row) => row.day} selectedKey={drawer.selectedId}
        onSelect={(row) => drawer.openView(row.day)} filterPlaceholder="篩選日期…"
      />
      <Drawer
        open={open} title={drawer.mode === "new" ? "新增日期" : selected ? fullDay(selected.day) : ""} onClose={drawer.close}
        footer={canManage && drawer.mode === "view" && selected
          ? <DayActions key={selected.day} day={selected} onEdit={() => drawer.openEdit(selected.day)} onDeleted={drawer.close} /> : undefined}
      >
        {drawer.mode === "new" && <CalendarDayForm onDone={drawer.close} />}
        {drawer.mode === "edit" && selected && <CalendarDayForm key={selected.day} day={selected} onDone={() => drawer.openView(selected.day)} />}
        {drawer.mode === "view" && selected && (
          <DetailList items={[["日期", fullDay(selected.day)], ["種類", <KindTag key="k" day={selected} />], ["名稱", selected.name]]} />
        )}
      </Drawer>
    </div>
  );
}
