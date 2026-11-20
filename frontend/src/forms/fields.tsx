import { useId, type ReactNode } from "react";

interface BaseProps { label: string; error?: string; required?: boolean }

function Field({ label, error, id, children }: { label: string; error?: string; id: string; children: ReactNode }) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children}
      {error && <div className="fieldError">{error}</div>}
    </div>
  );
}

type TextType = "text" | "email" | "password" | "number" | "date" | "datetime-local";

export function TextField({ label, error, required, type = "text", value, onChange, disabled }: BaseProps & {
  type?: TextType; value: string; onChange(value: string): void; disabled?: boolean;
}) {
  const id = useId();
  return (
    <Field label={label} error={error} id={id}>
      <input id={id} type={type} value={value} required={required} disabled={disabled} onChange={(e) => onChange(e.target.value)} />
    </Field>
  );
}

export function TextArea({ label, error, value, onChange }: BaseProps & { value: string; onChange(value: string): void }) {
  const id = useId();
  return (
    <Field label={label} error={error} id={id}>
      <textarea id={id} value={value} onChange={(e) => onChange(e.target.value)} />
    </Field>
  );
}

export interface Option { value: string; label: string }

export function SelectField({ label, error, required, value, onChange, options, allowEmpty }: BaseProps & {
  value: string; onChange(value: string): void; options: Option[];
  // 空選項的文字，例如「（無）」；不給就沒有空選項
  allowEmpty?: string;
}) {
  const id = useId();
  return (
    <Field label={label} error={error} id={id}>
      <select id={id} value={value} required={required} onChange={(e) => onChange(e.target.value)}>
        {allowEmpty !== undefined && <option value="">{allowEmpty}</option>}
        {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select>
    </Field>
  );
}

export function CheckList({ label, error, options, values, onChange }: BaseProps & {
  options: Option[]; values: string[]; onChange(values: string[]): void;
}) {
  const id = useId();
  const toggle = (value: string, checked: boolean) => onChange(checked ? [...values, value] : values.filter((item) => item !== value));
  return (
    <div className="field">
      <span className="fieldLabel" id={id}>{label}</span>
      <div className="checkList" role="group" aria-labelledby={id}>
        {options.length === 0 && <span className="empty">沒有可選的項目</span>}
        {options.map((option) => (
          <label key={option.value}>
            <input type="checkbox" checked={values.includes(option.value)} onChange={(e) => toggle(option.value, e.target.checked)} />
            {option.label}
          </label>
        ))}
      </div>
      {error && <div className="fieldError">{error}</div>}
    </div>
  );
}

export function CheckboxField({ label, checked, onChange }: { label: string; checked: boolean; onChange(checked: boolean): void }) {
  return (
    <label className="checkbox">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}
