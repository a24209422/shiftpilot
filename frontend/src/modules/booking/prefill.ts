import { parseLocal, toLocalString } from "../../forms/time";

export interface BookingPrefill { resourceId?: string; startAt?: string; endAt?: string }

// 轉一次再轉回來要一模一樣，才能擋掉 2 月 30 日這種格式對、日期不存在的值
const isLocalDateTime = (value: string) =>
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value) && toLocalString(parseLocal(value)) === value;

// 網址是使用者可以亂改的，不合法的值就當作沒帶，讓表單用原本的預設
export function readPrefill(params: URLSearchParams): BookingPrefill {
  const prefill: BookingPrefill = {};
  const resourceId = params.get("resourceId");
  if (resourceId && /^\d+$/.test(resourceId)) prefill.resourceId = resourceId;
  const startAt = params.get("startAt");
  const endAt = params.get("endAt");
  // 同一種格式的字串比大小就是時間先後
  if (startAt && endAt && isLocalDateTime(startAt) && isLocalDateTime(endAt) && startAt < endAt) {
    prefill.startAt = startAt;
    prefill.endAt = endAt;
  }
  return prefill;
}
