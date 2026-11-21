import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState, type CSSProperties, type FormEvent, type KeyboardEvent, type PointerEvent } from "react";
import { ApiError, apiGet, apiSend } from "../api/client";
import type { QaAnswer, QaModel } from "../api/types";
import { usePermissions } from "../auth/usePermissions";
import { addDays, formatDay, toLocalDate } from "../forms/time";
import { Icon } from "./icons";
import { ChatMessage, type ChatEntry } from "./QaMessage";

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
  const [model, setModel] = useState("");
  const [entries, setEntries] = useState<ChatEntry[]>([]);
  const [range, setRange] = useState<{ from: string; to: string } | null>(null);
  const [asking, setAsking] = useState(false);
  const nextId = useRef(1);
  // state 要等下一次 render 才更新，連按兩次時用 ref 才擋得住第二次
  const askingRef = useRef(false);

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

  async function onSend(event: FormEvent) {
    event.preventDefault();
    const text = question.trim();
    if (!text || !canAsk || !model || askingRef.current) return;
    const questionId = nextId.current++;
    const pendingId = nextId.current++;
    setEntries((current) => [...current, { id: questionId, kind: "question", text }, { id: pendingId, kind: "pending" }]);
    setQuestion("");
    askingRef.current = true;
    setAsking(true);
    try {
      const result = await apiSend<QaAnswer>("POST", "/api/qa/ask", { question: text, model });
      setRange(result.window);
      setEntries((current) => current.map((entry) => (entry.id === pendingId ? { id: pendingId, kind: "answer", result } : entry)));
    } catch (caught) {
      const error = caught instanceof ApiError ? caught : new ApiError(0, "UNKNOWN", "問答失敗，請再試一次");
      const sql = (error.details as { sql?: string } | null)?.sql ?? null;
      setEntries((current) => current.map((entry) => (entry.id === pendingId ? { id: pendingId, kind: "error", message: error.message, sql } : entry)));
    } finally {
      askingRef.current = false;
      setAsking(false);
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
                <span className="onDesktop"><Icon name="chevron" size={16} /></span>
                <span className="onMobile"><Icon name="close" size={16} /></span>
              </button>
            </div>
          </header>
          <div className="chatLog" role="log" aria-live="polite">
            <div className="msg bot">
              <div className="msgMeta">DESK</div>
              {/* 權限還在載入時先顯示說明，免得有權限的人先閃過一句「沒有權限」 */}
              <div className="bubble">{canAsk || permissionsLoading ? "用中文問組織、會議、請假或班表，例如「黃志強明天上什麼班？」「下週二下午誰有空？」" : "沒有使用問答的權限"}</div>
            </div>
            {entries.map((entry) => <ChatMessage key={entry.id} entry={entry} />)}
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
              {noModels && <div className="chatNote">目前沒有可用的模型</div>}
              {selected?.remote && <div className="chatNote">問題與查詢結果會送到雲端廠商</div>}
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
