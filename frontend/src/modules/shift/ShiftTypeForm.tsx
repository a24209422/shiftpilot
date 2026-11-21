import { useState, type FormEvent } from "react";
import { apiSend } from "../../api/client";
import type { ShiftType } from "../../api/types";
import { SelectField, TextField } from "../../forms/fields";
import { FormError } from "../../forms/FormError";
import { useSubmit } from "../../forms/useSubmit";
import { useToast } from "../../shell/Toast";
import { hourOptions, shiftHours } from "./format";

export function ShiftTypeForm({ shiftType, onDone }: { shiftType?: ShiftType; onDone(): void }) {
  const toast = useToast();
  const [code, setCode] = useState("");
  const [name, setName] = useState(shiftType?.name ?? "");
  const [startTime, setStartTime] = useState("09:00");
  const [endTime, setEndTime] = useState("18:00");
  const [breakStart, setBreakStart] = useState("");
  const [breakEnd, setBreakEnd] = useState("");
  const { submit, pending, error, fieldErrors } = useSubmit(
    () => {
      if (shiftType) {
        // 時間建立後不能改（班是即時推算的，改了會讓過去的班跟著變），只送名稱
        if (name === shiftType.name) return Promise.resolve(undefined);
        return apiSend("PATCH", `/api/shift/types/${shiftType.id}`, { name });
      }
      return apiSend("POST", "/api/shift/types", {
        code, name, startTime, endTime, breakStart: breakStart || null, breakEnd: breakEnd || null,
      });
    },
    { onSuccess: () => { toast(shiftType ? "已更新班別" : "已新增班別"); onDone(); }, invalidate: [["shifts"]] },
  );
  return (
    <form className="form" onSubmit={(event: FormEvent) => { event.preventDefault(); void submit(); }}>
      {!shiftType && <TextField label="代碼" required value={code} onChange={setCode} error={fieldErrors.code} />}
      <TextField label="名稱" required value={name} onChange={setName} error={fieldErrors.name} />
      {shiftType ? (
        <div className="formNote">時間：{shiftHours(shiftType)}{shiftType.breakStart ? `，休息 ${shiftType.breakStart}–${shiftType.breakEnd}` : ""}（建立後不能修改）</div>
      ) : (
        <>
          <SelectField label="上班" value={startTime} onChange={setStartTime} options={hourOptions} error={fieldErrors.startTime} />
          <SelectField label="下班" value={endTime} onChange={setEndTime} options={hourOptions} error={fieldErrors.endTime} />
          <SelectField label="休息開始" value={breakStart} onChange={setBreakStart} options={hourOptions} allowEmpty="無" error={fieldErrors.breakStart} />
          <SelectField label="休息結束" value={breakEnd} onChange={setBreakEnd} options={hourOptions} allowEmpty="無" error={fieldErrors.breakEnd} />
        </>
      )}
      <FormError error={error} />
      <div className="formActions">
        <button className="primary" type="submit" disabled={pending}>儲存</button>
        <button className="secondary" type="button" onClick={onDone}>取消</button>
      </div>
    </form>
  );
}
