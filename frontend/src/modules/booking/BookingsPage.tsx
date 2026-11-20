import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { apiSend } from "../../api/client";
import type { Booking } from "../../api/types";
import { useAuth } from "../../auth/AuthProvider";
import { usePermissions } from "../../auth/usePermissions";
import { CheckboxField } from "../../forms/fields";
import { FormError } from "../../forms/FormError";
import { addDays, formatDay, formatRange, parseLocal, toLocalDate, toLocalString, weekStart } from "../../forms/time";
import { useSubmit } from "../../forms/useSubmit";
import { DataTable, type Column } from "../../shell/DataTable";
import { DetailList } from "../../shell/DetailList";
import { Drawer } from "../../shell/Drawer";
import { Icon } from "../../shell/icons";
import { PageHead } from "../../shell/PageHead";
import { useToast } from "../../shell/Toast";
import { useDrawerParams } from "../../shell/useDrawerParams";
import { BookingForm } from "./BookingForm";
import { useBookings } from "./queries";

const organizerOf = (booking: Booking) => booking.participants.find((item) => item.role === "organizer")?.name ?? "—";
const StatusTag = ({ booking }: { booking: Booking }) => (
  booking.status === "cancelled" ? <span className="tag mute">已取消</span> : <span className="tag ok">已確認</span>
);

const columns: Column<Booking>[] = [
  { label: "日期時間", render: (row) => formatRange(row.startAt, row.endAt), text: (row) => formatRange(row.startAt, row.endAt) },
  { label: "標題", render: (row) => row.title, text: (row) => row.title },
  { label: "類別", render: (row) => row.category, text: (row) => row.category },
  { label: "資源", render: (row) => row.resources.map((item) => item.name).join("、") || "—", text: (row) => row.resources.map((item) => item.name).join(" ") },
  { label: "主辦人", render: organizerOf, text: organizerOf },
  { label: "狀態", render: (row) => <StatusTag booking={row} />, text: (row) => (row.status === "cancelled" ? "已取消" : "已確認") },
];

function BookingActions({ booking, onEdit, onCancelled }: { booking: Booking; onEdit(): void; onCancelled(): void }) {
  const toast = useToast();
  const [confirming, setConfirming] = useState(false);
  const cancel = useSubmit(
    () => apiSend("POST", `/api/booking/bookings/${booking.id}/cancel`),
    { onSuccess: () => { toast("已取消排程"); onCancelled(); }, invalidate: [["bookings"], ["summary"]] },
  );
  return (
    <>
      <FormError error={cancel.error} />
      <button className="primary" type="button" onClick={onEdit}>編輯</button>
      <button className="danger" type="button" disabled={cancel.pending} onClick={(event) => {
        // 連點的第二下（detail > 1）不能直接當成「確定」，不然二次確認形同虛設
        if (event.detail > 1) return;
        if (confirming) void cancel.submit(); else setConfirming(true);
      }}>
        {confirming ? "確定取消？" : "取消排程"}
      </button>
    </>
  );
}

export function BookingsPage() {
  const { can } = usePermissions();
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const weekParam = params.get("week");
  const start = weekStart(weekParam ? parseLocal(weekParam) : new Date());
  const [includeCancelled, setIncludeCancelled] = useState(false);
  const { data, isSuccess } = useBookings(start, includeCancelled);
  const drawer = useDrawerParams();
  const bookings = data ?? [];
  const selected = bookings.find((item) => String(item.id) === drawer.selectedId) ?? null;

  // 換週、取消後這筆不在列表裡時，關掉面板，不能顯示舊資料
  useEffect(() => {
    if (isSuccess && (drawer.mode === "view" || drawer.mode === "edit") && !selected) drawer.close();
  }, [isSuccess, drawer.mode, selected]); // eslint-disable-line react-hooks/exhaustive-deps

  const goToWeek = (date: Date) => setParams({ week: toLocalDate(date) });
  const canModify = (booking: Booking) =>
    booking.status === "confirmed" && (booking.createdBy === user?.id || can("booking.writeAny"));
  const open = drawer.mode === "new" || (drawer.mode !== null && selected !== null);
  const lastDay = toLocalString(addDays(start, 6));

  return (
    <div className="inner">
      <PageHead
        headline="Events."
        sub={`排程・本週 ${bookings.length} 筆。一筆排程可以有多個資源，新增時會先檢查衝突`}
        action={can("booking.write") && <button className="primary" type="button" onClick={drawer.openNew}><Icon name="plus" size={16} />新增排程</button>}
      />
      <div className="weekBar">
        <button className="secondary" type="button" onClick={() => goToWeek(addDays(start, -7))}>上一週</button>
        <button className="secondary" type="button" onClick={() => goToWeek(new Date())}>本週</button>
        <button className="secondary" type="button" onClick={() => goToWeek(addDays(start, 7))}>下一週</button>
        <span className="range">{formatDay(toLocalString(start))} – {formatDay(lastDay)}</span>
        <CheckboxField label="含已取消" checked={includeCancelled} onChange={setIncludeCancelled} />
      </div>
      <DataTable
        columns={columns} rows={bookings} rowKey={(row) => String(row.id)} selectedKey={drawer.selectedId}
        onSelect={(row) => drawer.openView(String(row.id))} filterPlaceholder="篩選排程…" emptyText="這一週沒有排程"
      />
      <Drawer
        open={open} title={drawer.mode === "new" ? "新增排程" : selected?.title ?? ""} onClose={drawer.close}
        footer={drawer.mode === "view" && selected && canModify(selected)
          ? <BookingActions key={selected.id} booking={selected} onEdit={() => drawer.openEdit(String(selected.id))} onCancelled={drawer.close} /> : undefined}
      >
        {drawer.mode === "new" && <BookingForm onDone={drawer.close} />}
        {drawer.mode === "edit" && selected && <BookingForm key={selected.id} booking={selected} onDone={() => drawer.openView(String(selected.id))} />}
        {drawer.mode === "view" && selected && (
          <DetailList
            items={[
              ["標題", selected.title],
              ["時間", formatRange(selected.startAt, selected.endAt)],
              ["類別", selected.category],
              ["資源", selected.resources.map((item) => item.name).join("、") || "—"],
              ["主辦人", organizerOf(selected)],
              ["參加者", selected.participants.filter((item) => item.role === "attendee").map((item) => item.name).join("、") || "—"],
              ["備註", selected.note ?? "—"],
              ["建立時間", formatRange(selected.createdAt, selected.createdAt)],
              ["狀態", <StatusTag key="s" booking={selected} />],
            ]}
          />
        )}
      </Drawer>
    </div>
  );
}
