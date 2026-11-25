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
  intent: "判斷要辦的事",
  generate_query: "產生查詢",
  query: "查詢資料",
  model: "等待模型回應",
  tool: "執行查詢工具",
  proposal: "準備待確認的提議",
  compose: "整理回答",
};

// 後端工具名稱是給模型看的英文；畫面上換成使用者看得懂的說法，沒列到的新工具就直接顯示原名
const toolLabels: Record<string, string> = {
  run_sql: "查詢資料",
  find_available_people: "找有空的人",
  get_busy_periods: "查忙碌時段",
  find_available_resources: "找可用的會議室",
  propose_booking: "準備預約提議",
  propose_reschedule_booking: "準備改期提議",
  propose_cancel_booking: "準備取消提議",
  propose_leave: "準備請假提議",
  propose_withdraw_leave: "準備撤回請假提議",
};

function stepLabel(step: QaProgressStep): string {
  if (!step.tool) return labels[step.stage];
  return toolLabels[step.tool] ?? step.tool;
}

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
            <span className="qaProgressLabel">{stepLabel(step)}</span>
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
    <>
      <div className="qaProgress">
        <div className="qaProgressHeader">
          <span>{progress.accepted ? "已收到問題" : "正在送出"}</span>
          {/* 等待中秒數跟著「思考中」顯示；結束後思考中消失，總秒數改放回框裡 */}
          {!running && elapsed}
        </div>
        {running && current && (
          <span role="status" className="qaProgressAnnouncement">{stepLabel(current)}，{statuses[current.state].label}</span>
        )}
        {list}
      </div>
      {running && (
        <div className="qaThinking">
          <span className="qaThreeBody" aria-hidden="true"><span /><span /><span /></span>
          思考中
          {elapsed}
        </div>
      )}
    </>
  );
}
