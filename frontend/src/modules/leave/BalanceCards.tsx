import type { LeaveBalance } from "../../api/types";

function remainingText(balance: LeaveBalance): string {
  if (balance.remainingHours === null) return "不限";
  return `剩 ${balance.remainingHours} 小時`;
}

function periodText(balance: LeaveBalance): string | null {
  if (balance.quotaKind !== "seniority") return null;
  if (balance.periodStart === null) return "到職滿 6 個月後才有特休";
  return `年度 ${balance.periodStart} – ${balance.periodEnd}`;
}

export function BalanceCards({ balances }: { balances: LeaveBalance[] }) {
  return (
    <section className="balanceCards">
      {balances.map((balance) => (
        <div className="balanceCard" key={balance.leaveTypeId}>
          <div className="balanceName">{balance.leaveTypeName}</div>
          <div className="balanceValue">{remainingText(balance)}</div>
          <div className="balanceNote">已用 {balance.approvedHours} ／ 待核准 {balance.pendingHours}</div>
          {periodText(balance) && <div className="balanceNote">{periodText(balance)}</div>}
        </div>
      ))}
    </section>
  );
}
