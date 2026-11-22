import type { QaAnswer, QaStep } from "../api/types";

export type ChatEntry =
  | { id: number; kind: "question"; text: string }
  | { id: number; kind: "pending" }
  | { id: number; kind: "answer"; result: QaAnswer }
  | { id: number; kind: "error"; message: string; sql: string | null };

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

function StepList({ steps }: { steps: QaStep[] }) {
  return (
    <details>
      <summary>看工具步驟</summary>
      <ol className="qaSteps">{steps.map((step, index) => <li key={index}>{stepText(step)}</li>)}</ol>
    </details>
  );
}

export function ChatMessage({ entry }: { entry: ChatEntry }) {
  if (entry.kind === "question") {
    return <div className="msg user"><div className="bubble">{entry.text}</div></div>;
  }
  if (entry.kind === "pending") {
    return <div className="msg bot"><div className="msgMeta">DESK</div><div className="bubble">查詢中…</div></div>;
  }
  if (entry.kind === "error") {
    return (
      <div className="msg bot">
        <div className="msgMeta">DESK</div>
        <div className="bubble qaError" role="alert">
          {entry.message}
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
      <div className="bubble">
        {result.answer}
        {result.steps && result.steps.length > 0 && <StepList steps={result.steps} />}
        <details>
          <summary>看查詢結果</summary>
          <ResultTable result={result} />
          {/* agent 用固定邏輯的工具查到結果時沒有 SQL */}
          {result.sql && <pre className="mono qaSql">{result.sql}</pre>}
        </details>
      </div>
    </div>
  );
}
