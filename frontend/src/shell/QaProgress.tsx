import { useEffect, useState } from "react";
import type { QaProgressEvent, QaProgressStage, QaProgressStep } from "../api/types";

export type QaProgressSnapshot = {
  startedAt: number;
  finishedAt?: number;
  accepted: boolean;
  steps: QaProgressStep[];
};

export function applyQaProgress(progress: QaProgressSnapshot, event: QaProgressEvent): QaProgressSnapshot {
  if (event.type === "accepted") return { ...progress, accepted: true };
  const exists = progress.steps.some((step) => step.id === event.id);
  const steps = exists ? progress.steps.map((step) => step.id === event.id ? event : step) : [...progress.steps, event];
  return { ...progress, steps };
}

const labels: Record<QaProgressStage, string> = {
  prepare: "準備可查詢的資料",
  route: "選擇查詢方式",
  generate_query: "產生查詢",
  query: "查詢資料",
  model: "等待模型回應",
  tool: "執行查詢工具",
  proposal: "準備待確認的提議",
  compose: "整理回答",
};

const statuses = {
  running: { label: "進行中", icon: "" },
  done: { label: "已完成", icon: "✓" },
  failed: { label: "失敗", icon: "×" },
  unknown: { label: "狀態未確認", icon: "?" },
};

export function QaProgress({ progress, collapsed = false }: { progress: QaProgressSnapshot; collapsed?: boolean }) {
  const [now, setNow] = useState(Date.now);
  const running = progress.finishedAt === undefined;
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [running]);

  const seconds = Math.max(0, Math.floor(((progress.finishedAt ?? now) - progress.startedAt) / 1000));
  const elapsed = <time className="qaProgressTime" aria-live="off" dateTime={`PT${seconds}S`}>{seconds} 秒</time>;
  const list = progress.steps.length > 0 && (
    <ol className="qaProgressList" aria-label="問答步驟" aria-live="off">
      {progress.steps.map((step) => {
        const state = step.state === "running" && !running ? "unknown" : step.state;
        const { label, icon } = statuses[state];
        return (
          <li key={step.id} data-state={state}>
            <span className="qaProgressIcon" aria-hidden="true">{icon}</span>
            <span className="qaProgressLabel">{labels[step.stage]}</span>
            <span className="qaProgressStatus">{label}</span>
          </li>
        );
      })}
    </ol>
  );
  if (collapsed) {
    return (
      <details className="qaProgress">
        <summary><span>查看處理進度</span>{elapsed}</summary>
        {list || <p className="qaProgressHeader">已收到問題</p>}
      </details>
    );
  }
  const current = progress.steps.at(-1);
  return (
    <div className="qaProgress">
      <div className="qaProgressHeader">
        <span>{progress.accepted ? "已收到問題" : "正在送出"}</span>
        {elapsed}
      </div>
      {running && current && (
        <span role="status" className="qaProgressAnnouncement">{labels[current.stage]}，{statuses[current.state].label}</span>
      )}
      {list}
    </div>
  );
}
