import re
from dataclasses import dataclass
from datetime import datetime

from app.modules.qa import tools
from app.modules.qa.sandbox import SandboxData
from app.modules.qa.tools import ToolArgumentError, ToolResult

weekdayNames = "一二三四五六日"
ambiguousLimit = 5
noEmployeeError = "你的帳號沒有員工資料，不能預約或請假"
# 「陳志明（業務部）」「A 會議室(#3)」：括號裡的提示用來分辨同名的人或資源
qualifiedName = re.compile(r"^(.*?)\s*[（(]\s*(.+?)\s*[)）]\s*$")
idReference = re.compile(r"^#(\d+)$")

proposalDefinitions = [
  {"type": "function", "function": {
    "name": "propose_booking",
    "description": "提議預約一場會議，使用者確認後才會建立。提問者一定是主辦人，participants 不用寫自己。",
    "parameters": {"type": "object", "properties": {
      "title": {"type": "string", "description": "會議標題"},
      **tools.timeProperties,
      "participants": {"type": "array", "items": {"type": "string"}, "description": "其他參加者的姓名，可省略；同名時寫成「姓名（部門或員工編號）」"},
      "resources": {"type": "array", "items": {"type": "string"}, "description": "要預約的資源名稱，例如 A 會議室，可省略；同名時寫成「名稱（地點）」"},
      "note": {"type": "string", "description": "備註，可省略"},
    }, "required": ["title", "start", "end"]},
  }},
  {"type": "function", "function": {
    "name": "propose_reschedule_booking",
    "description": "提議把一場會議改到新的時間，使用者確認後才會修改。",
    "parameters": {"type": "object", "properties": {
      "bookingId": {"type": "integer", "description": "會議的 id（bookings.id）"}, **tools.timeProperties,
    }, "required": ["bookingId", "start", "end"]},
  }},
  {"type": "function", "function": {
    "name": "propose_cancel_booking",
    "description": "提議取消一場會議，使用者確認後才會取消。",
    "parameters": {"type": "object", "properties": {
      "bookingId": {"type": "integer", "description": "會議的 id（bookings.id）"},
    }, "required": ["bookingId"]},
  }},
  {"type": "function", "function": {
    "name": "propose_leave",
    "description": "提議替提問者請假，使用者確認後才會送出申請。",
    "parameters": {"type": "object", "properties": {
      "leaveType": {"type": "string", "description": "假別名稱，例如特休"},
      **tools.timeProperties,
      "reason": {"type": "string", "description": "請假原因，可省略"},
    }, "required": ["leaveType", "start", "end"]},
  }},
  {"type": "function", "function": {
    "name": "propose_withdraw_leave",
    "description": "提議撤回提問者自己待核准的請假申請，使用者確認後才會撤回。",
    "parameters": {"type": "object", "properties": {
      "requestId": {"type": "integer", "description": "請假申請的 id（leave_requests.id）"},
    }, "required": ["requestId"]},
  }},
]

proposalNames = {item["function"]["name"] for item in proposalDefinitions}


@dataclass
class Asker:
  employeeId: int
  name: str
  department: str | None


def findAsker(data: SandboxData, employeeId: int | None) -> Asker | None:
  if employeeId is None:
    return None
  departments = {row[0]: row[1] for row in data.rows["departments"]}
  for row in data.rows["employees"]:
    if row[0] == employeeId:
      return Asker(row[0], row[2], departments.get(row[3]))
  return None


def formatDay(value: datetime) -> str:
  # Python 的 weekday() 週一是 0，前端用的 getDay() 週日是 0；這裡直接用週一開頭的表
  return f"{value.month}/{value.day}（{weekdayNames[value.weekday()]}）"


def formatRange(start: datetime, end: datetime) -> str:
  # 跟前端 forms/time.formatRange 一字不差：同一天的短橫線不加空白，跨日的加空白
  if start.date() == end.date():
    return f"{formatDay(start)} {start:%H:%M}–{end:%H:%M}"
  return f"{formatDay(start)} {start:%H:%M} – {formatDay(end)} {end:%H:%M}"


def apiTime(value: datetime) -> str:
  # 寫入 API 的 parseLocalTime 收 YYYY-MM-DDTHH:MM
  return value.strftime("%Y-%m-%dT%H:%M")


def parseProposalRange(arguments: dict) -> tuple[datetime, datetime]:
  try:
    start, end = tools.parseRange(arguments)
  except ToolArgumentError as error:
    # parseRange 對 end < start 有自己的說法；提議工具把「相同」也算進來，統一成一句
    if str(error) == "end 不能早於 start":
      raise ToolArgumentError("結束時間要晚於開始時間")
    raise
  # 寫入 API 只收到分鐘；先捨掉秒數再比較，確認卡顯示的時間才會跟送出的一樣，也不會送出零長度的時段
  start, end = start.replace(second=0, microsecond=0), end.replace(second=0, microsecond=0)
  if end <= start:
    raise ToolArgumentError("結束時間要晚於開始時間")
  return start, end


def candidateLabel(candidate: tuple[int, str, list[str]]) -> str:
  _, name, hints = candidate
  return f"{name}（{'，'.join(hints)}）" if hints else name


def matchName(candidates: list[tuple[int, str, list[str]]], text: str) -> tuple[int, str]:
  idMatch = idReference.match(text)
  if idMatch:
    found = [item for item in candidates if item[0] == int(idMatch.group(1))]
    if not found:
      raise ToolArgumentError(f"找不到「{text}」")
    return found[0][0], found[0][1]
  qualifiers: list[str] = []
  qualified = qualifiedName.match(text)
  # 名稱本身就可能帶括號（例如「會議室(大)」），整串完全相同時不拆
  if qualified and qualified.group(1) and not any(item[1] == text for item in candidates):
    # 模型常把反問裡的整串提示照抄回來，所以括號內可以有多個，用逗號或頓號分開，每個都要符合
    text = qualified.group(1)
    qualifiers = [part.strip() for part in re.split(r"[，,、]", qualified.group(2)) if part.strip()]
  # 先找完全相同的，避免「alice」因為「alice 陳」也包含它而變成對到多個
  matches = [item for item in candidates if item[1] == text] or [item for item in candidates if text in item[1]]
  matches = [item for item in matches if all(part in item[2] for part in qualifiers)]
  if not matches:
    raise ToolArgumentError(f"找不到「{text}」" + (f"（{'，'.join(qualifiers)}）" if qualifiers else ""))
  if len(matches) > 1:
    shown = "、".join(candidateLabel(item) for item in matches[:ambiguousLimit])
    # 同名時只回姓名，模型怎麼回答都會再對到同樣幾個；附上提示並說明怎麼指定，才有辦法收斂
    raise ToolArgumentError(f"「{text}」對到多個：{shown}，請問是哪一位／哪一個？確定後可寫成「{candidateLabel(matches[0])}」或「#{matches[0][0]}」指定")
  return matches[0][0], matches[0][1]


def nameList(arguments: dict, name: str) -> list[str]:
  value = arguments.get(name)
  if value is None:
    return []
  if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
    raise ToolArgumentError(f"參數 {name} 要是文字陣列")
  return [item.strip() for item in value]


def requireId(arguments: dict, name: str) -> int:
  value = arguments.get(name)
  # bool 是 int 的子類別，要排除；模型偶爾會把數字寫成字串，一併接受
  if isinstance(value, bool):
    raise ToolArgumentError(f"參數 {name} 要是整數")
  if isinstance(value, int):
    return value
  # isdigit() 對「²」「①」也回 True，但 int() 轉不了；isdecimal() 收的字元 int() 都能轉
  if isinstance(value, str) and value.strip().isdecimal():
    return int(value.strip())
  raise ToolArgumentError(f"參數 {name} 要是整數")


def employeeNames(data: SandboxData) -> list[tuple[int, str]]:
  return [(row[0], row[2]) for row in data.rows["employees"]]


def resourceNames(data: SandboxData) -> list[tuple[int, str]]:
  return [(row[0], row[1]) for row in data.rows["resources"]]


def employeeCandidates(data: SandboxData) -> list[tuple[int, str, list[str]]]:
  departments = {row[0]: row[1] for row in data.rows["departments"]}
  return [
    (row[0], row[2], [hint for hint in (departments.get(row[3]), row[1], f"#{row[0]}") if hint])
    for row in data.rows["employees"]
  ]


def resourceCandidates(data: SandboxData) -> list[tuple[int, str, list[str]]]:
  # 地點也可能重複，最後一定附上 #id，保證每個候選都能被單獨指定
  return [(row[0], row[1], [hint for hint in (row[3], f"#{row[0]}") if hint]) for row in data.rows["resources"]]


def participantText(data: SandboxData, asker: Asker | None, employeeIds: list[int]) -> str:
  byId = dict(employeeNames(data))
  labels = ["你"] if asker is not None and asker.employeeId in employeeIds else []
  labels += [byId.get(employeeId, f"#{employeeId}") for employeeId in employeeIds if asker is None or employeeId != asker.employeeId]
  return "、".join(labels) or "（無）"


def resourceText(data: SandboxData, resourceIds: list[int]) -> str:
  byId = dict(resourceNames(data))
  return "、".join(byId.get(resourceId, f"#{resourceId}") for resourceId in resourceIds) or "不預約"


def item(label: str, value: str) -> dict:
  return {"label": label, "value": value}


def proposal(kind: str, method: str, path: str, body: dict | None, summary: list[dict], quote: dict | None = None) -> dict:
  return {"kind": kind, "request": {"method": method, "path": path, "body": body}, "summary": summary, "quote": quote}


def findBooking(data: SandboxData, arguments: dict, action: str) -> tuple:
  bookingId = requireId(arguments, "bookingId")
  for row in data.rows["bookings"]:
    if row[0] == bookingId:
      if bookingId not in data.modifiableBookingIds:
        raise ToolArgumentError(f"只有建立者或有權限的人可以{action}會議 #{bookingId}")
      return row
  raise ToolArgumentError(f"找不到會議 #{bookingId}，請先用查詢工具確認 id")


def bookingSummary(data: SandboxData, asker: Asker | None, booking: tuple, timeText: str) -> list[dict]:
  bookingId = booking[0]
  participantIds = [row[1] for row in data.rows["booking_participants"] if row[0] == bookingId]
  resourceIds = [row[1] for row in data.rows["booking_resources"] if row[0] == bookingId]
  return [
    item("標題", booking[1]), item("時間", timeText),
    item("參加者", participantText(data, asker, participantIds)), item("資源", resourceText(data, resourceIds)),
  ]


def proposeBooking(data: SandboxData, asker: Asker | None, arguments: dict) -> dict:
  if asker is None:
    raise ToolArgumentError(noEmployeeError)
  title = tools.requireText(arguments, "title")
  start, end = parseProposalRange(arguments)
  participantIds: list[int] = []
  for text in nameList(arguments, "participants"):
    employeeId, _ = matchName(employeeCandidates(data), text)
    # 提問者由 service 自動設成主辦人，不重複放進名單
    if employeeId != asker.employeeId and employeeId not in participantIds:
      participantIds.append(employeeId)
  resourceIds: list[int] = []
  for text in nameList(arguments, "resources"):
    resourceId, _ = matchName(resourceCandidates(data), text)
    if resourceId not in resourceIds:
      resourceIds.append(resourceId)
  body = {
    "title": title, "category": "會議", "startAt": apiTime(start), "endAt": apiTime(end),
    "resourceIds": resourceIds, "participantEmployeeIds": participantIds,
  }
  note = tools.optionalText(arguments, "note")
  if note:
    body["note"] = note
  summary = [
    item("標題", title), item("時間", formatRange(start, end)),
    item("參加者", participantText(data, asker, [asker.employeeId, *participantIds])), item("資源", resourceText(data, resourceIds)),
    item("類別", "會議"),
  ]
  # 確認卡要跟實際送出的 body 一致，有備註就一併列出
  if note:
    summary.append(item("備註", note))
  return proposal("booking.create", "POST", "/api/booking/bookings", body, summary)


def proposeRescheduleBooking(data: SandboxData, asker: Asker | None, arguments: dict) -> dict:
  booking = findBooking(data, arguments, "改期")
  start, end = parseProposalRange(arguments)
  timeText = f"{formatRange(booking[3], booking[4])} → {formatRange(start, end)}"
  body = {"startAt": apiTime(start), "endAt": apiTime(end)}
  return proposal("booking.reschedule", "PATCH", f"/api/booking/bookings/{booking[0]}", body, bookingSummary(data, asker, booking, timeText))


def proposeCancelBooking(data: SandboxData, asker: Asker | None, arguments: dict) -> dict:
  booking = findBooking(data, arguments, "取消")
  summary = bookingSummary(data, asker, booking, formatRange(booking[3], booking[4]))
  return proposal("booking.cancel", "POST", f"/api/booking/bookings/{booking[0]}/cancel", None, summary)


def proposeLeave(data: SandboxData, asker: Asker | None, arguments: dict) -> dict:
  if asker is None:
    raise ToolArgumentError(noEmployeeError)
  leaveTypeId, leaveTypeName = matchName([(typeId, name, []) for typeId, name in data.leaveTypes], tools.requireText(arguments, "leaveType"))
  start, end = parseProposalRange(arguments)
  reason = tools.optionalText(arguments, "reason") or ""
  body = {"leaveTypeId": leaveTypeId, "startAt": apiTime(start), "endAt": apiTime(end), "reason": reason}
  summary = [item("假別", leaveTypeName), item("時間", formatRange(start, end)), item("原因", reason or "（未填）")]
  # quote 用同一份 body 的複本，前端改其中一份不會影響另一份
  return proposal("leave.create", "POST", "/api/leave/requests", body, summary, {"path": "/api/leave/requests/quote", "body": dict(body)})


def proposeWithdrawLeave(data: SandboxData, asker: Asker | None, arguments: dict) -> dict:
  requestId = requireId(arguments, "requestId")
  row = next((row for row in data.rows["leave_requests"] if row[0] == requestId), None)
  if row is None or asker is None or row[1] != asker.employeeId or row[6] != "pending":
    raise ToolArgumentError("只能撤回自己待核准的申請")
  summary = [item("假別", row[2] or "（未知）"), item("時間", formatRange(row[3], row[4])), item("原因", row[7] or "（未填）")]
  return proposal("leave.withdraw", "POST", f"/api/leave/requests/{requestId}/withdraw", None, summary)


handlers = {
  "propose_booking": proposeBooking,
  "propose_reschedule_booking": proposeRescheduleBooking,
  "propose_cancel_booking": proposeCancelBooking,
  "propose_leave": proposeLeave,
  "propose_withdraw_leave": proposeWithdrawLeave,
}


def executeProposal(data: SandboxData, asker: Asker | None, name: str, arguments: dict) -> ToolResult:
  handler = handlers.get(name)
  if handler is None:
    return tools.failed(f"沒有 {name} 這個工具，只能用 {', '.join(handlers)}")
  if not isinstance(arguments, dict):
    return tools.failed("參數不是合法的 JSON 物件")
  try:
    result = handler(data, asker, arguments)
  except ToolArgumentError as error:
    return tools.failed(str(error))
  return ToolResult(True, [], [], False, None, None, result)
