import type { ReactNode } from "react";

export function PageHead({ headline, sub, action }: { headline: string; sub?: string; action?: ReactNode }) {
  return (
    <header className="pageHead">
      <div>
        <h1 className="headline">{headline}</h1>
        {sub && <p className="sub">{sub}</p>}
      </div>
      {action}
    </header>
  );
}
