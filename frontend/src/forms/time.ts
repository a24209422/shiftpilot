const weekdayNames = ["日", "一", "二", "三", "四", "五", "六"];
const pad = (value: number) => String(value).padStart(2, "0");

// 後端給的是不帶時區的本地時間字串。自己切欄位建 Date，不讓瀏覽器去猜 ISO 字串的時區
export function parseLocal(value: string): Date {
  const [datePart, timePart = "00:00"] = value.split("T");
  const [year, month, day] = datePart.split("-").map(Number);
  const [hour, minute] = timePart.split(":").map(Number);
  return new Date(year, month - 1, day, hour, minute);
}

export const formatDay = (value: string) => {
  const date = parseLocal(value);
  return `${date.getMonth() + 1}/${date.getDate()}（${weekdayNames[date.getDay()]}）`;
};

export const formatTime = (value: string) => {
  const date = parseLocal(value);
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`;
};

export function formatRange(startAt: string, endAt: string): string {
  const sameDay = startAt.slice(0, 10) === endAt.slice(0, 10);
  if (sameDay) return `${formatDay(startAt)} ${formatTime(startAt)}–${formatTime(endAt)}`;
  return `${formatDay(startAt)} ${formatTime(startAt)} – ${formatDay(endAt)} ${formatTime(endAt)}`;
}

export const toInputValue = (value: string) => value.slice(0, 16);

export function addDays(date: Date, days: number): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() + days, date.getHours(), date.getMinutes());
}

// 週一 00:00（本地時間）
export function weekStart(date: Date): Date {
  const sinceMonday = (date.getDay() + 6) % 7;
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() - sinceMonday);
}

// 不用 toISOString：它會換成 UTC，台灣的凌晨會變成前一天
export const toLocalDate = (date: Date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
export const toLocalString = (date: Date) => `${toLocalDate(date)}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
