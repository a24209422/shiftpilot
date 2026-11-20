import { parseLocal, toLocalDate, toLocalString } from "../forms/time";
import type { TimelineSubject } from "./types";

export const dayMinutes = 24 * 60;
export const slotStep = 30;
const slotLength = 60;
const defaultAxis = { startMinute: 8 * 60, endMinute: 20 * 60 };
const pad = (value: number) => String(value).padStart(2, "0");

export interface Span { startMinute: number; endMinute: number; crossesDay: boolean }
export interface Axis { startMinute: number; endMinute: number }

// 台灣沒有日光節約時間，兩個本地時間直接相減就是分鐘差
const minutesFrom = (day: Date, value: string) => Math.round((parseLocal(value).getTime() - day.getTime()) / 60000);

export function clipToDay(day: Date, item: { startAt: string; endAt: string }): Span | null {
  const rawStart = minutesFrom(day, item.startAt);
  const rawEnd = minutesFrom(day, item.endAt);
  if (rawEnd <= 0 || rawStart >= dayMinutes) return null;
  return {
    startMinute: Math.max(0, rawStart),
    endMinute: Math.min(dayMinutes, rawEnd),
    crossesDay: rawStart < 0 || rawEnd > dayMinutes,
  };
}

export function axisFor(spans: Span[]): Axis {
  return spans.reduce((axis, span) => ({
    startMinute: Math.min(axis.startMinute, Math.floor(span.startMinute / 60) * 60),
    endMinute: Math.max(axis.endMinute, Math.ceil(span.endMinute / 60) * 60),
  }), defaultAxis);
}

export const percentOf = (axis: Axis, minute: number) =>
  ((minute - axis.startMinute) / (axis.endMinute - axis.startMinute)) * 100;

// 點某個 30 分鐘格子時要新增的時段：不早於前一筆的結束、不晚於下一筆的開始；整格被蓋住就沒有空檔
export function slotFor(cellStart: number, rowSpans: Span[]): { startMinute: number; endMinute: number } | null {
  let startMinute = cellStart;
  let moved = true;
  // 前後緊接的排程要一路跳過，所以重複找到沒有項目蓋住為止
  while (moved) {
    moved = false;
    for (const span of rowSpans) {
      if (span.startMinute <= startMinute && span.endMinute > startMinute) {
        startMinute = span.endMinute;
        moved = true;
      }
    }
  }
  if (startMinute >= cellStart + slotStep) return null;
  const nextStarts = rowSpans.filter((span) => span.startMinute > startMinute).map((span) => span.startMinute);
  return { startMinute, endMinute: Math.min(startMinute + slotLength, ...nextStarts) };
}

// 用 Date 處理超過 24:00 的分鐘數，跨到隔天時日期會自己進位
export const minuteToLocal = (day: Date, minute: number) =>
  toLocalString(new Date(day.getFullYear(), day.getMonth(), day.getDate(), 0, minute));

export const minuteLabel = (minute: number) => `${pad(Math.floor(minute / 60))}:${pad(minute % 60)}`;

// 12:00 到 13:00 那一欄算上午（午休前），下午從 13:00 開始
const morningEnd = 13 * 60;

// 表頭上層：以 13:00 切成上午、下午；橫軸整段都在 13:00 前（或後）時只有一段
export function halfDayGroups(axis: Axis): { label: string; startMinute: number; endMinute: number }[] {
  const groups = [];
  if (axis.startMinute < morningEnd) groups.push({ label: "上午", startMinute: axis.startMinute, endMinute: Math.min(morningEnd, axis.endMinute) });
  if (axis.endMinute > morningEnd) groups.push({ label: "下午", startMinute: Math.max(morningEnd, axis.startMinute), endMinute: axis.endMinute });
  return groups;
}

// 網址的日期格式錯或不存在（例如 2 月 30 日）時用今天，不讓整頁壞掉
export function parseDay(value: string | null, now: Date): Date {
  if (value && /^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const day = parseLocal(value);
    if (toLocalDate(day) === value) return day;
  }
  return new Date(now.getFullYear(), now.getMonth(), now.getDate());
}

export function groupSubjects(subjects: TimelineSubject[]): { name: string; subjects: TimelineSubject[] }[] {
  const groups: { name: string; subjects: TimelineSubject[] }[] = [];
  for (const subject of subjects) {
    const last = groups[groups.length - 1];
    if (last && last.name === subject.group) last.subjects.push(subject);
    else groups.push({ name: subject.group, subjects: [subject] });
  }
  return groups;
}
