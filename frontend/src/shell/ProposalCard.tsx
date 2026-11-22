import { useEffect, useRef, useState } from "react";
import { ApiError, apiSend } from "../api/client";
import type { LeaveQuote, QaProposal } from "../api/types";
import { useSubmit } from "../forms/useSubmit";
import { ConflictNotice } from "../modules/booking/ConflictNotice";
import { MeetingWarning } from "../modules/leave/MeetingWarning";
import { DetailList } from "./DetailList";

type Status = "open" | "done" | "cancelled" | "failed";

const doneText: Record<QaProposal["kind"], string> = {
  "booking.create": "建立了會議",
  "booking.reschedule": "改了會議時間",
  "booking.cancel": "取消了會議",
  "leave.create": "送出了請假申請",
  "leave.withdraw": "撤回了請假申請",
};
// 這幾種是警告或撞期，交給各自的提示畫明細（有些可以「仍要送出」），不算送出失敗
const conflictCodes = new Set(["RESOURCE_CONFLICT", "PARTICIPANT_CONFLICT", "MEETING_CONFLICT"]);

// 助理提議的動作：使用者按確認才真的呼叫寫入 API，結果寫回對話讓下一輪模型知道
export function ProposalCard({ proposal, active, onNote }: { proposal: QaProposal; active: boolean; onNote(text: string): void }) {
  const [status, setStatus] = useState<Status>("open");
  const [quote, setQuote] = useState<LeaveQuote | null>(null);
  const [quoteError, setQuoteError] = useState<ApiError | null>(null);
  // 「仍要送出」只對下一次送出有效，用過就清掉
  const acknowledge = useRef(false);
  // SidePanel 每次 render 都給新的 onNote，放 ref 才不會讓錯誤的 effect 重跑而重複記錄
  const onNoteRef = useRef(onNote);
  onNoteRef.current = onNote;
  const { request } = proposal;

  useEffect(() => {
    if (proposal.kind !== "leave.create" || !proposal.quote) return;
    let stale = false;
    apiSend<LeaveQuote>("POST", proposal.quote.path, proposal.quote.body)
      .then((result) => { if (!stale) setQuote(result); })
      .catch((caught) => { if (!stale) setQuoteError(caught instanceof ApiError ? caught : new ApiError(0, "UNKNOWN", "試算失敗")); });
    return () => { stale = true; };
  }, [proposal]);

  const { submit, pending, error } = useSubmit(
    () => {
      const ack = acknowledge.current;
      acknowledge.current = false;
      // 取消、撤回沒有 body，不能硬塞 acknowledgeWarnings
      const body = request.body === null ? undefined : ack ? { ...request.body, acknowledgeWarnings: true } : request.body;
      return apiSend<{ id: number }>(request.method, request.path, body);
    },
    {
      onSuccess: (result) => {
        setStatus("done");
        onNoteRef.current(`（系統紀錄）使用者已確認，${doneText[proposal.kind]} #${result.id}`);
      },
      invalidate: proposal.kind.startsWith("booking.") ? [["bookings"], ["summary"]] : [["leave"]],
    },
  );

  useEffect(() => {
    if (!error || conflictCodes.has(error.code)) return;
    setStatus("failed");
    onNoteRef.current(`（系統紀錄）送出失敗：${error.message}`);
  }, [error]);

  const override = () => {
    if (pending) return;
    acknowledge.current = true;
    void submit();
  };
  const cancel = () => {
    setStatus("cancelled");
    onNoteRef.current("（系統紀錄）使用者取消了這個提議");
  };
  const superseded = !active && status === "open";
  // 舊卡失敗後也不讓重試，免得對已經被取代的提議送出
  const showActions = active && (status === "open" || status === "failed");

  return (
    <div className="qaProposal">
      <DetailList items={proposal.summary.map((item) => [item.label, item.value])} />
      {quote && <div className="formNote">時數 {quote.hours} 小時</div>}
      {quote && quote.remainingAfter !== null && <div className="formNote">扣完剩 {quote.remainingAfter} 小時</div>}
      {quote && quote.conflicts.length > 0 && (
        <div className="formWarn">這段時間你有會議：{[...new Set(quote.conflicts.map((item) => item.title))].join("、")}</div>
      )}
      {quoteError && <div className="formError" role="alert">{quoteError.message}</div>}
      {showActions && <ConflictNotice error={error} pending={pending} onOverride={override} />}
      {showActions && <MeetingWarning error={error} pending={pending} onOverride={override} />}
      {error && !conflictCodes.has(error.code) && <div className="formError" role="alert">{error.message}</div>}
      {status === "done" && <div className="formNote">已完成</div>}
      {status === "cancelled" && <div className="formNote">已取消</div>}
      {superseded && <div className="formNote">已被新的提議取代</div>}
      {showActions && (
        <div className="formActions">
          <button className="primary" type="button" disabled={pending || quoteError !== null} onClick={() => void submit()}>確認</button>
          <button className="secondary" type="button" disabled={pending} onClick={cancel}>取消</button>
        </div>
      )}
    </div>
  );
}
