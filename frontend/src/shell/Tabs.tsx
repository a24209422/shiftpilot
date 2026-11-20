interface Tab { key: string; label: string }

export function Tabs({ tabs, value, onChange }: { tabs: Tab[]; value: string; onChange(key: string): void }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.key} type="button" role="tab" aria-selected={tab.key === value}
          className={tab.key === value ? "tab active" : "tab"} onClick={() => onChange(tab.key)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
