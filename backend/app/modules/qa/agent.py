from dataclasses import dataclass, field

from psycopg import Connection

from app.modules.qa import sqlguard, tools
from app.modules.qa.tools import ToolResult

# 一題最多 4 次工具呼叫：小模型容易在同一個錯誤上打轉，次數太多只會讓使用者等更久
maxToolCalls = 4


@dataclass
class AgentOutcome:
  answer: str
  result: ToolResult | None
  steps: list[dict] = field(default_factory=list)
  toolCalls: int = 0
  exhausted: bool = False
  promptTokens: int = 0
  completionTokens: int = 0
  proposal: dict | None = None


def fallbackAnswer(result: ToolResult) -> str:
  return f"查到 {len(result.rows)}{' 筆以上' if result.truncated else ' 筆'}資料。"


def runAgent(
  conn: Connection, toolLlm, model: str, messages: list[dict], allowedTools: list[str] | None = None,
  *, definitions: list[dict] | None = None, execute=None, maxCalls: int = maxToolCalls,
) -> AgentOutcome:
  outcome = AgentOutcome(answer="", result=None)
  messages = list(messages)
  execute = execute or tools.executeTool
  # allowedTools 是 None 時全部給（agent 模式）；jev 模式只給 Jev 選中的那一個
  definitions = tools.toolDefinitions if definitions is None else definitions
  if allowedTools is not None:
    definitions = [item for item in definitions if item["function"]["name"] in allowedTools]
  while True:
    reply = toolLlm(model, messages, definitions)
    outcome.promptTokens += reply.promptTokens or 0
    outcome.completionTokens += reply.completionTokens or 0
    if not reply.toolCalls:
      outcome.answer = sqlguard.stripThink(reply.content).strip()
      break
    messages.append({"role": "assistant", "content": reply.content, "toolCalls": reply.toolCalls})
    for toolCall in reply.toolCalls:
      if outcome.toolCalls >= maxCalls:
        outcome.exhausted = True
        break
      if allowedTools is not None and toolCall.name not in allowedTools:
        # 只給了被選中的工具，模型仍可能照記憶呼叫別的；不執行，告訴它能用什麼
        result = tools.failed(f"這題只能用 {', '.join(allowedTools)}")
      else:
        result = execute(conn, toolCall.name, toolCall.arguments)
      outcome.toolCalls += 1
      outcome.steps.append({
        "tool": toolCall.name, "arguments": toolCall.arguments,
        "rowCount": len(result.rows) if result.ok else None, "error": result.error,
      })
      messages.append({"role": "tool", "toolCallId": toolCall.id, "name": toolCall.name, "content": tools.formatForModel(result)})
      if result.proposal is not None:
        # 提議要等使用者確認，後面的呼叫不能搶先執行；也不算查詢結果，表格維持上一個
        outcome.proposal = result.proposal
        break
      if result.ok:
        outcome.result = result
    if outcome.proposal is not None:
      outcome.answer = sqlguard.stripThink(reply.content).strip() or "請確認以下內容。"
      break
    # 用完次數就停，不再呼叫模型收尾：多一次呼叫只是多等，答案表格已經有了
    if outcome.exhausted or outcome.toolCalls >= maxCalls:
      outcome.exhausted = True
      break
  # Ollama 解析 tool call 模板失敗時，呼叫會變成 <tool_call> 純文字；那不是給人看的回答
  if outcome.proposal is None and outcome.result is not None and (outcome.exhausted or not outcome.answer or "<tool_call>" in outcome.answer):
    outcome.answer = fallbackAnswer(outcome.result)
  return outcome
