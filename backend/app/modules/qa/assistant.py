from collections.abc import Callable

from psycopg import Connection

from app.modules.qa import proposals, tools
from app.modules.qa.proposals import Asker
from app.modules.qa.sandbox import SandboxData
from app.modules.qa.tools import ToolArgumentError, ToolResult

# 助理要多一步查詢再提議，上限比其他模式的 4 高；agent.maxToolCalls 維持不動
maxAssistantToolCalls = 6

resourceKinds = ["room", "equipment", "vehicle"]

findResourcesDefinition = {"type": "function", "function": {
  "name": "find_available_resources",
  "description": "找出指定時段沒有被預約的資源（會議室、設備、車輛）。",
  "parameters": {"type": "object", "properties": {
    **tools.timeProperties,
    "kind": {"type": "string", "enum": resourceKinds, "description": "資源種類，會議室是 room，可省略"},
    "minCapacity": {"type": "integer", "description": "最少要容納的人數，可省略"},
  }, "required": ["start", "end"]},
}}

# 只存在於助理模式：不放進 tools.toolDefinitions / handlers，其他模式的工具清單才不會變
assistantToolDefinitions = [*tools.toolDefinitions, findResourcesDefinition, *proposals.proposalDefinitions]

availableResourcesSql = """
SELECT r.name, r.kind, r.location, r.capacity
FROM resources r
WHERE (%(kind)s::text IS NULL OR r.kind = %(kind)s)
  AND (%(minCapacity)s::int IS NULL OR r.capacity >= %(minCapacity)s)
  AND NOT EXISTS (SELECT 1 FROM booking_resources br JOIN bookings b ON b.id = br.booking_id
    WHERE br.resource_id = r.id AND b.start_at < %(end)s AND b.end_at > %(start)s)
ORDER BY r.capacity NULLS LAST, r.id
"""


def findAvailableResources(conn: Connection, arguments: dict) -> ToolResult:
  start, end = tools.parseRange(arguments)
  kind = tools.optionalText(arguments, "kind")
  if kind is not None and kind not in resourceKinds:
    raise ToolArgumentError(f"kind 只能是 {', '.join(resourceKinds)}，收到：{kind}")
  minCapacity = arguments.get("minCapacity")
  # bool 是 int 的子類別，要先排除
  if minCapacity is not None and (isinstance(minCapacity, bool) or not isinstance(minCapacity, int)):
    raise ToolArgumentError("minCapacity 要是整數")
  params = {"start": start, "end": end, "kind": kind, "minCapacity": minCapacity}
  return tools.runFixed(conn, availableResourcesSql, params)


def executeAssistantTool(conn: Connection, name: str, arguments: dict | None) -> ToolResult:
  if name != "find_available_resources":
    return tools.executeTool(conn, name, arguments)
  if not isinstance(arguments, dict):
    return tools.failed("參數不是合法的 JSON 物件")
  try:
    return findAvailableResources(conn, arguments)
  except ToolArgumentError as error:
    return tools.failed(str(error))


def makeExecutor(data: SandboxData, asker: Asker | None) -> Callable[[Connection, str, dict | None], ToolResult]:
  def execute(conn: Connection, name: str, arguments: dict | None) -> ToolResult:
    # 提議工具只讀沙盒資料快照，不碰連線，所以不可能寫入
    if name in proposals.proposalNames:
      return proposals.executeProposal(data, asker, name, arguments)
    return executeAssistantTool(conn, name, arguments)
  return execute
