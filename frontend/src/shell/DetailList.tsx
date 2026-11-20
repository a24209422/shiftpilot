import type { ReactNode } from "react";

export function DetailList({ items }: { items: [label: string, value: ReactNode][] }) {
  return (
    <dl>
      {items.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}
