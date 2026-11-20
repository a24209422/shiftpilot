import type { ResourceKind } from "../../api/types";

export const resourceKindLabels: Record<ResourceKind, string> = { room: "會議室", equipment: "設備", vehicle: "公務車" };
export const resourceKindTones: Record<ResourceKind, string> = { room: "ok", equipment: "warn", vehicle: "info" };
