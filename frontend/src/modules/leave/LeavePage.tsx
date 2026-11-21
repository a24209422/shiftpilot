import { useSearchParams } from "react-router";
import type { LeaveRequest } from "../../api/types";
import { useAuth } from "../../auth/AuthProvider";
import { usePermissions } from "../../auth/usePermissions";
import { formatDay, formatRange, formatTime } from "../../forms/time";
import { DataTable, type Column } from "../../shell/DataTable";
import { DetailList } from "../../shell/DetailList";
import { Drawer } from "../../shell/Drawer";
import { Icon } from "../../shell/icons";
import { PageHead } from "../../shell/PageHead";
import { Tabs } from "../../shell/Tabs";
import { useDrawerParams } from "../../shell/useDrawerParams";
import { BalanceCards } from "./BalanceCards";
import { statusLabels, statusTones } from "./labels";
import { LeaveRequestForm } from "./LeaveRequestForm";
import { useLeaveBalances, useLeaveRequest, useLeaveRequests } from "./queries";
import { ApprovalActions, OwnerActions } from "./RequestActions";

const StatusTag = ({ request }: { request: LeaveRequest }) => <span className={`tag ${statusTones[request.status]}`}>{statusLabels[request.status]}</span>;

export const requestColumns: Column<LeaveRequest>[] = [
  { label: "時間", render: (row) => formatRange(row.startAt, row.endAt), text: (row) => formatRange(row.startAt, row.endAt) },
  { label: "假別", render: (row) => row.leaveTypeName, text: (row) => row.leaveTypeName },
  { label: "時數", render: (row) => `${row.hours} 小時`, text: (row) => String(row.hours) },
  { label: "事由", render: (row) => row.reason || "—", text: (row) => row.reason },
  { label: "狀態", render: (row) => <StatusTag request={row} />, text: (row) => statusLabels[row.status] },
];

export function RequestDetail({ request }: { request: LeaveRequest }) {
  return (
    <DetailList
      items={[
        ["申請人", request.employeeName],
        ["假別", request.leaveTypeName],
        ["時間", formatRange(request.startAt, request.endAt)],
        ["時數", `${request.hours} 小時`],
        ["事由", request.reason || "—"],
        ["狀態", <StatusTag key="s" request={request} />],
        ["核准人", request.decidedByName ?? "—"],
        ["決定時間", request.decidedAt ? `${formatDay(request.decidedAt)} ${formatTime(request.decidedAt)}` : "—"],
        ["備註", request.decisionNote ?? "—"],
      ]}
    />
  );
}

export function LeavePage() {
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const drawer = useDrawerParams();
  const { can } = usePermissions();
  const hasEmployee = user?.employeeId != null;
  const balances = useLeaveBalances(null, hasEmployee);
  const mine = useLeaveRequests("mine", hasEmployee);
  // 詳情一律依 id 讀：主管、人資從時間軸點進來看的是別人的假，不在「我的申請」裡
  const detail = useLeaveRequest(drawer.mode === "view" ? drawer.selectedId : null);
  const toApprove = useLeaveRequests("toApprove");
  // 只有真的有東西要核准（或是人資）才出現，一般員工不會看到空的分頁
  const showApprove = can("leave.manage") || (toApprove.data?.length ?? 0) > 0;
  const requestedTab = params.get("tab");
  const tab = requestedTab === "approve" && showApprove ? "approve" : "mine";
  const tabs = [{ key: "mine", label: "我的申請" }, ...(showApprove ? [{ key: "approve", label: "待我核准" }] : [])];
  const setTab = (key: string) => setParams((current) => {
    const next = new URLSearchParams(current);
    next.set("tab", key);
    ["id", "new", "edit"].forEach((name) => next.delete(name));
    return next;
  });
  const selected = detail.data ?? null;
  const inToApprove = selected !== null && (toApprove.data ?? []).some((item) => item.id === selected.id);
  // 人資可以核准任何人（本人除外）：主管還在職時申請不會出現在人資的待核准清單，但後端允許
  const canDecide = selected !== null && selected.status === "pending"
    && (inToApprove || (can("leave.manage") && user?.employeeId !== selected.employeeId));
  const open = drawer.mode === "new" || (drawer.mode === "view" && selected !== null);

  return (
    <div className="inner">
      <PageHead
        headline="Time off"
        action={hasEmployee && <button className="primary" type="button" onClick={drawer.openNew}><Icon name="plus" size={16} />申請請假</button>}
      />
      {!hasEmployee && <div className="empty">這個帳號沒有對應的員工，不能請假</div>}
      {hasEmployee && balances.data && <BalanceCards balances={balances.data} />}
      <Tabs tabs={tabs} value={tab} onChange={setTab} />
      {tab === "mine" && hasEmployee && (
        <DataTable
          columns={requestColumns} rows={mine.data ?? []} rowKey={(row) => String(row.id)} selectedKey={drawer.selectedId}
          onSelect={(row) => drawer.openView(String(row.id))} filterPlaceholder="篩選申請…" emptyText="還沒有請假申請"
        />
      )}
      {tab === "approve" && (
        <DataTable
          columns={[{ label: "申請人", render: (row) => row.employeeName, text: (row) => row.employeeName }, ...requestColumns]}
          rows={toApprove.data ?? []} rowKey={(row) => String(row.id)} selectedKey={drawer.selectedId}
          onSelect={(row) => drawer.openView(String(row.id))} filterPlaceholder="篩選申請…" emptyText="沒有待核准的申請"
        />
      )}
      <Drawer
        open={open} title={drawer.mode === "new" ? "申請請假" : selected ? `${selected.employeeName}的${selected.leaveTypeName}` : ""} onClose={drawer.close}
        footer={drawer.mode === "view" && selected ? (
          canDecide
            ? <ApprovalActions key={selected.id} request={selected} onDone={drawer.close} />
            : <OwnerActions key={selected.id} request={selected} onDone={drawer.close} />
        ) : undefined}
      >
        {drawer.mode === "new" && <LeaveRequestForm onDone={drawer.close} />}
        {drawer.mode === "view" && selected && <RequestDetail request={selected} />}
      </Drawer>
    </div>
  );
}
