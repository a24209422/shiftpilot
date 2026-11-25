import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type FormEvent, type KeyboardEvent, type PointerEvent } from "react";
import { ApiError, apiGet } from "../api/client";
import { askWithProgress } from "../api/qaStream";
import type { QaIntent, QaMode, QaModel, QaSettings } from "../api/types";
import { usePermissions } from "../auth/usePermissions";
import { addDays, formatDay, toLocalDate } from "../forms/time";
import { Icon } from "./icons";
import { useDevMode } from "./devMode";
import { ChatMessage, previousTurnFor, toHistory, type ChatEntry } from "./QaMessage";
import { applyQaProgress, type QaProgressSnapshot } from "./QaProgress";

// 跟後端的沙盒範圍一致：還沒問過問題前，先用今天前後各 90 天提示
const windowDays = 90;

const defaultWidth = 400;
const minWidth = 320;
// 上限取視窗的 60%，不然拉太寬會把主內容擠到看不見
const maxWidth = () => Math.max(minWidth, Math.min(760, Math.round(window.innerWidth * 0.6)));
const clamp = (width: number) => Math.min(maxWidth(), Math.max(minWidth, Math.round(width)));
const mobileQuery = "(max-width: 760px)";
const isMobile = () => typeof window.matchMedia === "function" && window.matchMedia(mobileQuery).matches;

// 問答（text2sql）面板：模型清單與回答都來自後端，沒有 qa.ask 權限時只顯示說明
export function SidePanel() {
  const [width, setWidth] = useState(defaultWidth);
  // 桌面預設展開；手機上展開會蓋滿整個畫面，所以預設收起來
  const [open, setOpen] = useState(() => !isMobile());
  const [question, setQuestion] = useState("");
  const { can, isLoading: permissionsLoading } = usePermissions();
  const canAsk = can("qa.ask");
  const { data: models, isLoading: modelsLoading } = useQuery({ queryKey: ["qa", "models"], queryFn: () => apiGet<QaModel[]>("/api/qa/models"), enabled: canAsk });
  const { data: settings } = useQuery({ queryKey: ["qa", "settings"], queryFn: () => apiGet<QaSettings>("/api/qa/settings"), enabled: canAsk });
  const [model, setModel] = useState("");
  const devMode = useDevMode();
  const [mode, setMode] = useState<QaMode>("assistant-jev");
  // 模式選單只給開發者；關掉開發者模式時，之前選過什麼都不算，一律用唯一入口
  const sentMode: QaMode = devMode ? mode : "assistant-jev";
  const [entries, setEntries] = useState<ChatEntry[]>([]);
  const [range, setRange] = useState<{ from: string; to: string } | null>(null);
  const [asking, setAsking] = useState(false);
  const nextId = useRef(1);
  // state 要等下一次 render 才更新，連按兩次時用 ref 才擋得住第二次
  const askingRef = useRef(false);
  const requestRef = useRef<AbortController | null>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const followChat = useRef(true);
  useEffect(() => () => requestRef.current?.abort(), []);
  useLayoutEffect(() => {
    const log = logRef.current;
    if (log && open && followChat.current) log.scrollTop = log.scrollHeight;
  }, [entries, open]);

  // 模型清單載入後預設第一個（後端把 .env 的 OLLAMA_MODEL 放第一）
  useEffect(() => {
    // 新清單不含目前選的模型（含清單變空）就重設，免得送出已經不存在的模型
    if (!models) return;
    if (!models.some((item) => item.id === model)) setModel(models[0]?.id ?? "");
  }, [models, model]);
  const noModels = canAsk && !modelsLoading && (models?.length ?? 0) === 0;

  const selected = models?.find((item) => item.id === model);
  const today = new Date();
  const shownRange = range ?? { from: toLocalDate(addDays(today, -windowDays)), to: toLocalDate(addDays(today, windowDays)) };

  // 確認卡做完動作後補一行系統紀錄，下一輪對話模型才知道動作成功或失敗
  const addNote = (text: string) => setEntries((current) => [...current, { id: nextId.current++, kind: "note", text }]);
  // 只有最後一張確認卡能按，避免使用者對已經改過的舊提議按確認
  const activeProposalId = entries.reduce<number | null>((last, entry) => (entry.kind === "answer" && entry.result.proposal ? entry.id : last), null);

  async function onSend(event: FormEvent) {
    event.preventDefault();
    const text = question.trim();
    if (!text || !canAsk || !model || askingRef.current) return;
    const questionId = nextId.current++;
    const pendingId = nextId.current++;
    const progress: QaProgressSnapshot = { startedAt: Date.now(), accepted: false, steps: [] };
    const controller = new AbortController();
    requestRef.current = controller;
    followChat.current = true;
    setEntries((current) => [...current, { id: questionId, kind: "question", text }, { id: pendingId, kind: "pending", progress }]);
    const updatePending = (update: (progress: QaProgressSnapshot) => ChatEntry) => {
      setEntries((current) => current.map((entry) => entry.id === pendingId && entry.kind === "pending" ? update(entry.progress) : entry));
    };
    setQuestion("");
    askingRef.current = true;
    setAsking(true);
    try {
      // history 取發問前的紀錄（此時 entries 還是 render 當下的值，不含這一題）；只有兩種助理模式會讀
      const isAssistant = sentMode === "assistant" || sentMode === "assistant-jev";
      const previous = sentMode === "assistant-jev" ? previousTurnFor(entries) : null;
      const body = {
        question: text, model, mode: sentMode,
        ...(isAssistant ? { history: toHistory(entries) } : {}),
        ...(previous?.intent ? { previousIntent: previous.intent } : {}),
        ...(previous?.openProposal ? { openProposal: previous.openProposal } : {}),
      };
      const result = await askWithProgress(body, (event) => {
        if (!controller.signal.aborted) {
          updatePending((current) => ({ id: pendingId, kind: "pending", progress: applyQaProgress(current, event) }));
        }
      }, controller.signal);
      if (controller.signal.aborted) return;
      setRange(result.window);
      const finishedAt = Date.now();
      updatePending((current) => ({ id: pendingId, kind: "answer", result, progress: { ...current, finishedAt } }));
    } catch (caught) {
      if (controller.signal.aborted) return;
      const error = caught instanceof ApiError ? caught : new ApiError(0, "UNKNOWN", "問答失敗，請再試一次");
      const details = error.details as { sql?: string; intent?: QaIntent } | null;
      const sql = details?.sql ?? null;
      const intent = details?.intent ?? null;
      const finishedAt = Date.now();
      updatePending((current) => ({ id: pendingId, kind: "error", message: error.message, sql, intent, progress: { ...current, finishedAt } }));
    } finally {
      requestRef.current = null;
      askingRef.current = false;
      if (!controller.signal.aborted) setAsking(false);
    }
  }

  useEffect(() => {
    // 視窗縮小時上限會跟著變，要重新夾一次
    const onResize = () => setWidth((current) => clamp(current));
    window.addEventListener("resize", onResize);
    if (typeof window.matchMedia !== "function") return () => window.removeEventListener("resize", onResize);
    const query = window.matchMedia(mobileQuery);
    const onChange = () => setOpen(!query.matches);
    query.addEventListener("change", onChange);
    return () => {
      window.removeEventListener("resize", onResize);
      query.removeEventListener("change", onChange);
    };
  }, []);

  const startDrag = useCallback((event: PointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = width;
    document.body.classList.add("dragging");
    // 面板在右邊，把手往左拖 = 變寬；監聽掛在 window，滑鼠甩出把手範圍時才不會中斷
    const onMove = (moveEvent: globalThis.PointerEvent) => setWidth(clamp(startWidth + (startX - moveEvent.clientX)));
    const onUp = () => {
      document.body.classList.remove("dragging");
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
  }, [width]);

  function onHandleKey(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "ArrowLeft") { event.preventDefault(); setWidth(clamp(width + 24)); }
    if (event.key === "ArrowRight") { event.preventDefault(); setWidth(clamp(width - 24)); }
    if (event.key === "Home") { event.preventDefault(); setWidth(defaultWidth); }
  }

  return (
    <>
      <aside className={`chat${open ? "" : " collapsed"}`} aria-label="問答面板" style={{ "--chat-w": `${width}px` } as CSSProperties}>
        <div
          className="resizer" role="separator" aria-orientation="vertical" aria-label="調整問答面板寬度" tabIndex={0}
          aria-valuemin={minWidth} aria-valuemax={maxWidth()} aria-valuenow={width}
          onPointerDown={startDrag} onKeyDown={onHandleKey} onDoubleClick={() => setWidth(defaultWidth)}
        />
        <button className="chatRail" type="button" aria-label="展開問答面板" title="展開問答面板" onClick={() => setOpen(true)}>
          <Icon name="chat" size={20} />
          <span className="vertical">Ask the desk</span>
        </button>
        <div className="chatFull">
          <header className="chatHead">
            <div>
              <div className="chatTitle">Ask the desk</div>
            </div>
            <div className="chatActions">
              <button className="iconBtn" type="button" title="收合" aria-label="收合問答面板" onClick={() => setOpen(false)}>
                <span className="onDesktop"><Icon name="panelRight" size={18} /></span>
                <span className="onMobile"><Icon name="close" size={16} /></span>
              </button>
            </div>
          </header>
          <div className="chatLog" role="log" aria-live="polite" ref={logRef} onScroll={({ currentTarget }) => {
            followChat.current = currentTarget.scrollHeight - currentTarget.clientHeight - currentTarget.scrollTop <= 16;
          }}>
            <div className="msg bot">
              <div className="msgMeta">DESK</div>
              {/* 權限還在載入時先顯示說明，免得有權限的人先閃過一句「沒有權限」 */}
              <div className="bubble">{canAsk || permissionsLoading ? "我可以幫你查組織、班表、會議和請假，也可以幫你約會議、改期或取消，或是請假、撤回假單。例如「黃志強明天上什麼班？」「幫我約林小美下週二下午開會」" : "沒有使用問答的權限"}</div>
            </div>
            {entries.map((entry) => <ChatMessage key={entry.id} entry={entry} proposalActive={entry.id === activeProposalId} onNote={addNote} />)}
          </div>
          <form className="chatForm" onSubmit={onSend}>
            <div className="chatFormRow">
              <textarea
                className="chatInput" aria-label="問題" rows={2} placeholder="用中文問排程，例如「明天有哪些會議？」"
                value={question} onChange={(event) => setQuestion(event.target.value)}
                onKeyDown={(event) => {
                  // Enter 送出、Shift+Enter 換行；輸入法選字時的 Enter 不算
                  if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); }
                }}
              />
              <button className="chatSend" type="submit" aria-label="送出" title="送出" disabled={!canAsk || asking || !model}><Icon name="arrowUp" size={20} /></button>
            </div>
            <div className="chatFormBar">
              <select className="chatModel" aria-label="模型" value={model} onChange={(event) => setModel(event.target.value)} disabled={!canAsk}>
                {(models ?? []).map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
              </select>
              {devMode && (
                <select className="chatModel" aria-label="模式" value={mode} onChange={(event) => setMode(event.target.value as QaMode)} disabled={!canAsk}>
                  <option value="pipeline">舊流程</option>
                  <option value="agent">Agent</option>
                  <option value="jev">Agent＋Jev</option>
                  <option value="assistant">助理</option>
                  <option value="assistant-jev">助理＋Jev</option>
                </select>
              )}
              <button className="chatClear" type="button" onClick={() => setEntries([])} disabled={entries.length === 0 || asking}>清除對話</button>
              {noModels && <div className="chatNote">目前沒有可用的模型</div>}
              {selected?.remote && <div className="chatNote">問題與查詢結果會送到雲端廠商</div>}
              {/* 本機模型也一樣：有設 Jev 時，問題文字會先送到 TypeSafe */}
              {settings?.jevConfigured && sentMode === "assistant-jev" && <div className="chatNote">問題文字會送到 Jev（TypeSafe）判斷意圖</div>}
              {settings?.jevConfigured && sentMode === "jev" && <div className="chatNote">問題文字會送到 Jev（TypeSafe）選工具</div>}
              <div className="chatNote">資料範圍：{formatDay(shownRange.from)} ～ {formatDay(shownRange.to)}</div>
            </div>
          </form>
        </div>
      </aside>
      {!open && (
        <button className="fab" type="button" onClick={() => setOpen(true)}><Icon name="chat" size={18} />Ask</button>
      )}
    </>
  );
}
