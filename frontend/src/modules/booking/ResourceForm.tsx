import { useState, type FormEvent } from "react";
import { apiSend } from "../../api/client";
import type { Resource, ResourceKind } from "../../api/types";
import { SelectField, TextArea, TextField } from "../../forms/fields";
import { FormError } from "../../forms/FormError";
import { useSubmit } from "../../forms/useSubmit";
import { useToast } from "../../shell/Toast";
import { resourceKindLabels } from "./labels";

const kindOptions = (Object.keys(resourceKindLabels) as ResourceKind[]).map((value) => ({ value, label: resourceKindLabels[value] }));
const sameList = (a: string[], b: string[]) => a.length === b.length && a.every((item, index) => item === b[index]);

export function ResourceForm({ resource, onDone }: { resource?: Resource; onDone(): void }) {
  const toast = useToast();
  const [name, setName] = useState(resource?.name ?? "");
  const [kind, setKind] = useState<string>(resource?.kind ?? "room");
  const [location, setLocation] = useState(resource?.location ?? "");
  const [capacity, setCapacity] = useState(resource?.capacity?.toString() ?? "");
  const [features, setFeatures] = useState(resource?.features.join("、") ?? "");
  const [note, setNote] = useState(resource?.note ?? "");

  const values = {
    name,
    kind,
    location: location || null,
    capacity: capacity === "" ? null : Number(capacity),
    features: features.split(/[,，、]/).map((item) => item.trim()).filter(Boolean),
    note: note || null,
  };

  const { submit, pending, error, fieldErrors } = useSubmit(
    async () => {
      if (!resource) return apiSend("POST", "/api/booking/resources", values);
      // 只送改過的欄位：PATCH 裡的 null 代表「清空」，沒改的欄位不能帶
      const changed: Record<string, unknown> = {};
      if (values.name !== resource.name) changed.name = values.name;
      if (values.kind !== resource.kind) changed.kind = values.kind;
      if (values.location !== resource.location) changed.location = values.location;
      if (values.capacity !== resource.capacity) changed.capacity = values.capacity;
      if (!sameList(values.features, resource.features)) changed.features = values.features;
      if (values.note !== resource.note) changed.note = values.note;
      if (Object.keys(changed).length === 0) return undefined;
      return apiSend("PATCH", `/api/booking/resources/${resource.id}`, changed);
    },
    { onSuccess: () => { toast(resource ? "已更新資源" : "已新增資源"); onDone(); }, invalidate: [["resources"], ["summary"]] },
  );

  return (
    <form className="form" onSubmit={(event: FormEvent) => { event.preventDefault(); void submit(); }}>
      <TextField label="名稱" required value={name} onChange={setName} error={fieldErrors.name} />
      <SelectField label="種類" value={kind} onChange={setKind} options={kindOptions} error={fieldErrors.kind} />
      <TextField label="地點" value={location} onChange={setLocation} error={fieldErrors.location} />
      <TextField label="容量" type="number" value={capacity} onChange={setCapacity} error={fieldErrors.capacity} />
      <TextField label="特色（用逗號分隔）" value={features} onChange={setFeatures} error={fieldErrors.features} />
      <TextArea label="備註" value={note} onChange={setNote} error={fieldErrors.note} />
      <FormError error={error} />
      <div className="formActions">
        <button className="primary" type="submit" disabled={pending}>儲存</button>
        <button className="secondary" type="button" onClick={onDone}>取消</button>
      </div>
    </form>
  );
}
