import { useCallback, useEffect, useState, type CSSProperties, type FormEvent, type KeyboardEvent, type PointerEvent } from "react";
import { Icon } from "./icons";
import { useToast } from "./Toast";

// 只是介面的樣子：接上後端時換成真的模型清單
const modelOptions = ["qwen2.5:3b", "qwen3-vl:4b-instruct"];

const defaultWidth = 400;
const minWidth = 320;
// 上限取視窗的 60%，不然拉太寬會把主內容擠到看不見
const maxWidth = () => Math.max(minWidth, Math.min(760, Math.round(window.innerWidth * 0.6)));
const clamp = (width: number) => Math.min(maxWidth(), Math.max(minWidth, Math.round(width)));
const mobileQuery = "(max-width: 760px)";
const isMobile = () => typeof window.matchMedia === "function" && window.matchMedia(mobileQuery).matches;

// 問答（text2sql）的位置：外殼與輸入區的樣子先做好（收合、拖曳寬度、選模型、送出），功能還沒接後端，所以不放假答案
export function SidePanel() {
  const [width, setWidth] = useState(defaultWidth);
  // 桌面預設展開；手機上展開會蓋滿整個畫面，所以預設收起來
  const [open, setOpen] = useState(() => !isMobile());
  const [question, setQuestion] = useState("");
  const [model, setModel] = useState(modelOptions[0]);
  const toast = useToast();

  // 問答還沒接後端：送出不產生任何回答，輸入的字留著，只說明還沒開放
  function onSend(event: FormEvent) {
    event.preventDefault();
    toast("問答尚未開放");
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
          <div className="chatLog">
            <div className="msg bot">
              <div className="msgMeta">DESK</div>
              <div className="bubble">問答尚未開放。之後可以在這裡用中文查詢排程，例如「明天有哪些會議？」。</div>
            </div>
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
              <button className="chatSend" type="submit" aria-label="送出" title="送出"><Icon name="arrowUp" size={20} /></button>
            </div>
            <div className="chatFormBar">
              <select className="chatModel" aria-label="模型" value={model} onChange={(event) => setModel(event.target.value)}>
                {modelOptions.map((option) => <option key={option} value={option}>{option}</option>)}
              </select>
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
