import { useState } from "react";
import type { UnusedLeave } from "../../api/types";
import { TextField } from "../../forms/fields";
import { toLocalDate } from "../../forms/time";
import { DataTable, type Column } from "../../shell/DataTable";
import { useUnused } from "./queries";

const columns: Column<UnusedLeave>[] = [
  { label: "員工", render: (row) => row.employeeName, text: (row) => row.employeeName },
  { label: "部門", render: (row) => row.departmentName, text: (row) => row.departmentName },
  { label: "年度", render: (row) => `${row.periodStart} – ${row.periodEnd}`, text: (row) => row.periodEnd },
  { label: "額度", render: (row) => `${row.quotaHours + row.adjustmentHours} 小時`, text: (row) => String(row.quotaHours) },
  { label: "已用", render: (row) => `${row.usedHours} 小時`, text: (row) => String(row.usedHours) },
  { label: "未休", render: (row) => `${row.unusedHours} 小時`, text: (row) => String(row.unusedHours) },
];

export function UnusedReport() {
  const today = new Date();
  // 預設今年 1/1 到今天：人資通常在結算時看「已經結束」的年度
  const [from, setFrom] = useState(`${today.getFullYear()}-01-01`);
  const [to, setTo] = useState(toLocalDate(today));
  const { data } = useUnused(from, to);
  return (
    <>
      <div className="weekBar">
        <TextField label="年度結束日從" type="date" value={from} onChange={setFrom} />
        <TextField label="到" type="date" value={to} onChange={setTo} />
      </div>
      <DataTable
        columns={columns} rows={data ?? []} rowKey={(row) => `${row.employeeId}-${row.periodStart}`}
        selectedKey={null} onSelect={() => {}} filterPlaceholder="篩選…" emptyText="這段期間沒有未休的特休"
      />
    </>
  );
}
