import type { QaAnswer, QaHistoryItem, QaIntent, QaIntentName, QaProposal, QaRoute, QaStep } from "../api/types";
import { ProposalCard } from "./ProposalCard";
import { QaProgress, type QaProgressSnapshot } from "./QaProgress";

export type ChatEntry =
  | { id: number; kind: "question"; text: string }
  | { id: number; kind: "pending"; progress: QaProgressSnapshot }
  | { id: number; kind: "answer"; result: QaAnswer; progress?: QaProgressSnapshot }
  | { id: number; kind: "error"; message: string; sql: string | null; intent?: QaIntent | null; progress?: QaProgressSnapshot }
  | { id: number; kind: "note"; text: string };

// 後端上限：最多 40 則、每則 1000 字；超過會被 422 擋掉，所以送出前先裁
const historyMaxItems = 40;
const historyMaxChars = 1000;

// 提議的內容只在確認卡上，不附上去的話，下一輪模型不知道自己提議了什麼（例如「換一間」要換掉哪一間）
const answerText = (result: QaAnswer) => {
  if (!result.proposal) return result.answer;
  const summary = result.proposal.summary.map((item) => `${item.label}=${item.value}`).join("；");
  return `${result.answer}\n（提議：${summary}）`;
};

// 只送真正的對話：等待中與錯誤沒有內容，不放進去；系統紀錄用 user 角色，模型才看得到動作結果
export function toHistory(entries: ChatEntry[]): QaHistoryItem[] {
  const items: QaHistoryItem[] = [];
  for (const entry of entries) {
    if (entry.kind === "question" || entry.kind === "note") items.push({ role: "user", content: entry.text });
    else if (entry.kind === "answer") items.push({ role: "assistant", content: answerText(entry.result) });
  }
  return items.slice(-historyMaxItems).map((item) => ({ role: item.role, content: item.content.slice(0, historyMaxChars) }));
}

// 上一則是反問（只有文字）或還沒處理的提議時，單看下一句判斷不出意圖，沿用上一輪的工具組；
// 確認或取消後會補一則系統紀錄，最後一則就不是 answer，下一題重新問 Jev
const proposalIntents: Record<QaProposal["kind"], QaIntentName> = {
  "booking.create": "booking", "booking.reschedule": "manageBooking", "booking.cancel": "manageBooking",
  "leave.create": "leave", "leave.withdraw": "leave",
};

export interface PreviousTurn { intent: QaIntentName | "all" | null; openProposal: QaIntentName | null }

// 還沒處理的確認卡：最後一張帶提議的回覆，後面沒有系統紀錄（確認、取消、送出失敗都會補一則）
function openCardIntent(entries: ChatEntry[]): QaIntentName | null {
  for (let index = entries.length - 1; index >= 0; index -= 1) {
    const entry = entries[index];
    if (entry.kind === "note") return null;
    if (entry.kind === "answer" && entry.result.proposal) {
      // 沒有 intent 的卡片來自開發者模式的其他模式，後端不會合併
      return entry.result.intent ? proposalIntents[entry.result.proposal.kind] : null;
    }
  }
  return null;
}

// 上一則是反問時要沿用的意圖；上一則本身是確認卡時由 openCardIntent 處理
function reusedIntent(entries: ChatEntry[]): QaIntentName | "all" | null {
  const last = entries[entries.length - 1];
  if (!last || last.kind !== "answer") return null;
  const { result } = last;
  if (!result.intent || result.proposal || result.rows.length > 0) return null;
  // 沒設 key 時不沿用：後端每一則都重新判斷，面板才會一直標出「沒設定 Jev」
  if (result.intent.fallbackReason === "not_configured") return null;
  // 上一輪合併過時，反問多半是針對新加的那件事
  const name = result.intent.addedName ?? result.intent.name;
  // query 組沒有提議工具：沿用它的話，被誤判成查詢的辦事請求之後怎麼說都辦不了，所以重新問 Jev
  if (name === "query") return null;
  return name ?? "all";
}

// 卡片還開著時，不管中間問了什麼，都把卡片的意圖一起送出，後端會合併工具組並再問 Jev，回頭改卡片才辦得到
export function previousTurnFor(entries: ChatEntry[]): PreviousTurn | null {
  const intent = reusedIntent(entries);
  const openProposal = openCardIntent(entries);
  return intent || openProposal ? { intent, openProposal } : null;
}

// 物件與陣列直接 String() 會變成 [object Object]，改用 JSON 才看得出內容
const cellText = (value: unknown) => {
  if (value === null || value === undefined) return "—";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
};

function ResultTable({ result }: { result: QaAnswer }) {
  if (result.columns.length === 0) return <div className="empty">沒有資料</div>;
  return (
    <div className="qaTable">
      <table>
        <thead><tr>{/* SELECT a.name, b.name 會有同名欄位，key 要帶順序 */}
          {result.columns.map((column, index) => <th key={`${index}-${column}`} scope="col">{column}</th>)}</tr></thead>
        <tbody>
          {result.rows.map((row, rowIndex) => (
            <tr key={rowIndex}>{row.map((value, columnIndex) => <td key={columnIndex}>{cellText(value)}</td>)}</tr>
          ))}
        </tbody>
      </table>
      {result.rows.length === 0 && <div className="empty">查無資料</div>}
      {result.truncated && <div className="chatNote">只顯示前 {result.rows.length} 筆</div>}
    </div>
  );
}

// 參數值依模型給的順序列出，展示 agent 時看得出它每一步怎麼填參數
const stepText = (step: QaStep) => {
  const args = Object.values(step.arguments ?? {}).map(cellText).join("，");
  const outcome = step.error === null ? `${step.rowCount ?? 0} 筆` : `失敗：${step.error}`;
  return `${step.tool}（${args}）→ ${outcome}`;
};

const fallbackText: Record<string, string> = { low_confidence: "信心不足", unavailable: "呼叫失敗", bad_response: "回應格式不對" };

const intentLabels: Record<QaIntentName, string> = { query: "查詢", booking: "預約會議", manageBooking: "改期或取消會議", leave: "請假或撤回請假" };

const intentText = (intent: QaIntent) => {
  if (intent.reused && intent.name && (intent.addedName || intent.cardName)) {
    const parts = [`沿用上一輪：${intentLabels[intent.name]}`];
    if (intent.cardName) parts.push(`還開著的確認卡：${intentLabels[intent.cardName]}`);
    if (intent.addedName) parts.push(`加上 Jev 判斷：${intentLabels[intent.addedName]}（信心 ${(intent.confidence ?? 0).toFixed(2)}）`);
    return parts.join("，");
  }
  if (intent.reused) return intent.name ? `沿用上一輪的意圖：${intentLabels[intent.name]}` : "沿用上一輪：9 個工具都給";
  if (intent.name) return `Jev 判斷：${intentLabels[intent.name]}（信心 ${(intent.confidence ?? 0).toFixed(2)}）`;
  if (intent.fallbackReason === "not_configured") return "沒設定 Jev，9 個工具都給";
  return `Jev 沒選定（${fallbackText[intent.fallbackReason ?? ""] ?? "原因不明"}），9 個工具都給`;
};

const routeText = (route: QaRoute) =>
  route.tool ? `Jev 選了 ${route.tool}（信心 ${(route.confidence ?? 0).toFixed(2)}）`
    : `Jev 沒選定（${fallbackText[route.fallbackReason ?? ""] ?? "原因不明"}），三個工具都給`;

function StepList({ steps, route, intent }: { steps: QaStep[]; route?: QaRoute; intent?: QaIntent }) {
  return (
    <details>
      <summary>看工具步驟</summary>
      {route && <p className="qaRoute">{routeText(route)}</p>}
      {intent && <p className="qaRoute">{intentText(intent)}</p>}
      <ol className="qaSteps">{steps.map((step, index) => <li key={index}>{stepText(step)}</li>)}</ol>
    </details>
  );
}

// proposalActive：這則是不是最後一則帶提議的回答，舊的提議要標成已被取代
export function ChatMessage({ entry, proposalActive = false, onNote = () => {} }: { entry: ChatEntry; proposalActive?: boolean; onNote?(text: string): void }) {
  if (entry.kind === "question") {
    return <div className="msg user"><div className="bubble">{entry.text}</div></div>;
  }
  if (entry.kind === "note") {
    return <div className="chatNote qaNote">{entry.text}</div>;
  }
  if (entry.kind === "pending") {
    return <div className="msg bot"><div className="msgMeta">DESK</div><QaProgress progress={entry.progress} /></div>;
  }
  if (entry.kind === "error") {
    return (
      <div className="msg bot">
        <div className="msgMeta">DESK</div>
        {entry.progress?.accepted && <QaProgress progress={entry.progress} />}
        <div className="bubble qaError" role="alert">
          {entry.message}
          {entry.intent && <p className="qaRoute">{intentText(entry.intent)}</p>}
          {entry.sql && <details><summary>看 SQL</summary><pre className="mono qaSql">{entry.sql}</pre></details>}
        </div>
      </div>
    );
  }
  const { result } = entry;
  return (
    <div className="msg bot">
      {/* 雲端模型要標出來：問題與查詢結果已經離開這台電腦 */}
      <div className="msgMeta">{result.model}{result.remote ? "・已送到雲端" : ""}</div>
      {entry.progress && <QaProgress progress={entry.progress} collapsed />}
      <div className="bubble">
        {result.answer}
        {((result.steps && result.steps.length > 0) || result.route || result.intent) && (
          <StepList steps={result.steps ?? []} route={result.route} intent={result.intent} />
        )}
        <details>
          <summary>看查詢結果</summary>
          <ResultTable result={result} />
          {/* agent 用固定邏輯的工具查到結果時沒有 SQL */}
          {result.sql && <pre className="mono qaSql">{result.sql}</pre>}
        </details>
        {result.proposal && <ProposalCard proposal={result.proposal} active={proposalActive} onNote={onNote} />}
      </div>
    </div>
  );
}
