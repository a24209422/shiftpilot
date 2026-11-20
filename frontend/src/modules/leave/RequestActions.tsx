import { useState } from "react";
import { apiSend } from "../../api/client";
import type { LeaveRequest } from "../../api/types";
import { useAuth } from "../../auth/AuthProvider";
import { usePermissions } from "../../auth/usePermissions";
import { TextArea } from "../../forms/fields";
import { FormError } from "../../forms/FormError";
import { parseLocal } from "../../forms/time";
import { useSubmit } from "../../forms/useSubmit";
import { useToast } from "../../shell/Toast";

// 二次確認：第一下變成「確定…？」，第二下才送出；連點的第二下（detail > 1）不算確認
function ConfirmButton({ label, confirmLabel, pending, onConfirm }: { label: string; confirmLabel: string; pending: boolean; onConfirm(): void }) {
  const [confirming, setConfirming] = useState(false);
  return (
    <button className="danger" type="button" disabled={pending} onClick={(event) => {
      if (event.detail > 1) return;
      if (confirming) onConfirm(); else setConfirming(true);
    }}>
      {confirming ? confirmLabel : label}
    </button>
  );
}

export function OwnerActions({ request, onDone }: { request: LeaveRequest; onDone(): void }) {
  const toast = useToast();
  const { user } = useAuth();
  const { can } = usePermissions();
  const withdraw = useSubmit(
    () => apiSend("POST", `/api/leave/requests/${request.id}/withdraw`),
    { onSuccess: () => { toast("已撤回申請"); onDone(); }, invalidate: [["leave"]] },
  );
  const cancel = useSubmit(
    () => apiSend("POST", `/api/leave/requests/${request.id}/cancel`),
    { onSuccess: () => { toast("已取消請假"); onDone(); }, invalidate: [["leave"]] },
  );
  const isOwner = user?.employeeId === request.employeeId;
  const notStarted = parseLocal(request.startAt) > new Date();
  const canWithdraw = isOwner && request.status === "pending";
  // 假開始後只有人資能取消：可能已經牽涉出勤與薪資
  const canCancel = request.status === "approved" && ((isOwner && notStarted) || can("leave.manage"));
  return (
    <>
      <FormError error={withdraw.error ?? cancel.error} />
      {canWithdraw && <ConfirmButton label="撤回" confirmLabel="確定撤回？" pending={withdraw.pending} onConfirm={() => void withdraw.submit()} />}
      {canCancel && <ConfirmButton label="取消請假" confirmLabel="確定取消？" pending={cancel.pending} onConfirm={() => void cancel.submit()} />}
    </>
  );
}

export function ApprovalActions({ request, onDone }: { request: LeaveRequest; onDone(): void }) {
  const toast = useToast();
  const [note, setNote] = useState("");
  const [noteError, setNoteError] = useState<string | undefined>();
  const approve = useSubmit(
    () => apiSend("POST", `/api/leave/requests/${request.id}/approve`, { note: note || null }),
    { onSuccess: () => { toast("已核准"); onDone(); }, invalidate: [["leave"]] },
  );
  const reject = useSubmit(
    () => apiSend("POST", `/api/leave/requests/${request.id}/reject`, { note }),
    { onSuccess: () => { toast("已退回"); onDone(); }, invalidate: [["leave"]] },
  );
  return (
    <div className="form">
      <TextArea label="核准備註或退回理由" value={note} onChange={(value) => { setNote(value); setNoteError(undefined); }} error={noteError} />
      <FormError error={approve.error ?? reject.error} />
      <div className="formActions">
        <button className="primary" type="button" disabled={approve.pending || reject.pending} onClick={() => void approve.submit()}>核准</button>
        <button className="danger" type="button" disabled={approve.pending || reject.pending} onClick={() => {
          // 前端先擋一次，少一趟來回；後端也會檢查
          if (!note.trim()) { setNoteError("退回要填理由"); return; }
          void reject.submit();
        }}>退回</button>
      </div>
    </div>
  );
}
