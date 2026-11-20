// TanStack Query 的 queryKey 與 queryFn；檢視與來源回傳這個，時間軸頁再交給 useQuery／useQueries
export interface TimelineQuery<T> {
  queryKey: readonly unknown[];
  queryFn: () => Promise<T>;
}

// 時間軸上的一個項目；所有模組共用這個格式
export interface TimelineItem {
  key: string;
  // 第一版只有長條；請假、排班要用時再加種類
  kind: "event";
  subjectId: number;
  startAt: string;
  endAt: string;
  label: string;
  link: string;
}

export interface TimelineSubject {
  id: number;
  label: string;
  // 時間軸頁依出現順序分組，不自己排序；排序由檢視決定
  group: string;
}

// 檢視決定每一列是什麼，由擁有那種對象的模組登記
export interface TimelineView {
  key: string;
  name: string;
  subjectType: string;
  requires: string;
  emptyText: string;
  subjects: () => TimelineQuery<TimelineSubject[]>;
  createRequires?: string;
  createLink?: (subjectId: number, startAt: string, endAt: string) => string;
}

// 來源提供長條，任何模組都可以登記；用 subjectType 對應到檢視
export interface TimelineSource {
  key: string;
  name: string;
  subjectType: string;
  requires: string;
  items: (from: string, to: string) => TimelineQuery<TimelineItem[]>;
}
