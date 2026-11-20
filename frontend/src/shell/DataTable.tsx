import { useState, type ReactNode } from "react";

export interface Column<T> {
  label: string;
  render(row: T): ReactNode;
  // 篩選時比對的文字
  text(row: T): string;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey(row: T): string;
  selectedKey: string | null;
  onSelect(row: T): void;
  filterPlaceholder: string;
  emptyText?: string;
}

export function DataTable<T>({ columns, rows, rowKey, selectedKey, onSelect, filterPlaceholder, emptyText = "沒有符合的資料" }: DataTableProps<T>) {
  const [keyword, setKeyword] = useState("");
  const needle = keyword.trim().toLowerCase();
  const visible = needle ? rows.filter((row) => columns.some((column) => column.text(row).toLowerCase().includes(needle))) : rows;
  return (
    <>
      <div className="toolbar">
        <input type="search" placeholder={filterPlaceholder} aria-label={filterPlaceholder} value={keyword} onChange={(e) => setKeyword(e.target.value)} />
      </div>
      <div className="tableWrap">
        <table>
          <thead><tr>{columns.map((column) => <th key={column.label}>{column.label}</th>)}</tr></thead>
          <tbody>
            {visible.length === 0 && <tr><td colSpan={columns.length} className="empty">{emptyText}</td></tr>}
            {visible.map((row) => {
              const key = rowKey(row);
              return (
                <tr key={key} className={key === selectedKey ? "selected" : ""} onClick={() => onSelect(row)}>
                  {columns.map((column) => <td key={column.label}>{column.render(row)}</td>)}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
