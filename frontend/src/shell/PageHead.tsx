import type { ReactNode } from "react";

export function PageHead({ headline, action }: { headline: string; action?: ReactNode }) {
  return (
    <header className="pageHead">
      <div>
        <h1 className="headline">{headline}</h1>
      </div>
      {action}
    </header>
  );
}
