"""評測用的固定公司資料。

資料一律透過各模組的服務函式建立：沙盒裡看到的班表、請假片段、權限可見度，才會跟正式系統算出來的一樣。
"""
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv

from app.config import buildQaDatabaseUrl
from app.infra.actor import Actor
from app.infra.db import openDb, temporarySchema
from app.infra.migrate import runMigrations
from app.modules import allModules
from app.modules.booking import service as bookingService
from app.modules.booking.service import BookingInput
from app.modules.leave import requests as leaveRequests
from app.modules.leave.requests import LeaveInput
from app.modules.org import service as orgService
from app.modules.shift import service as shiftService

# 「現在」固定在星期二下午：題目裡的「明天」「下週」每次都對到同一天
# 本週 11-16 ～ 11-22、上週 11-09 ～ 11-15、下週 11-23 ～ 11-29
fixedNow = datetime(2026, 11, 17, 14, 30)
askerNames = {"employee": "李佳穎", "requester": "林小美", "manager": "陳大文", "hr": "張雅婷"}

# (員工編號, 姓名, 部門, 職稱, 主管編號, 到職日, 角色)
employeeRows = [
  ("E009", "蔡明哲", "管理部", "總經理", None, date(2018, 1, 1), "manager"),
  ("E001", "陳大文", "工程部", "工程部經理", "E009", date(2020, 3, 1), "manager"),
  ("E005", "王建國", "業務部", "業務經理", "E009", date(2019, 9, 1), "manager"),
  ("E004", "張雅婷", "人資部", "人資專員", "E009", date(2021, 5, 1), "hr"),
  ("E011", "許淑芬", "人資部", "行政助理", "E009", date(2023, 4, 1), "employee"),
  ("E002", "林小美", "工程部", "工程師", "E001", date(2022, 7, 1), "employee"),
  ("E003", "黃志強", "工程部", "工程師", "E001", date(2023, 2, 1), "employee"),
  ("E008", "劉怡君", "工程部", "測試工程師", "E001", date(2024, 6, 1), "employee"),
  ("E010", "鄭家豪", "工程部", "維運工程師", "E001", date(2023, 8, 1), "employee"),
  ("E006", "李佳穎", "業務部", "業務專員", "E005", date(2024, 1, 15), "employee"),
  ("E007", "吳宗翰", "業務部", "業務專員", "E005", date(2025, 3, 1), "employee"),
  ("E012", "周志明", "業務部", "業務專員", "E005", date(2022, 1, 1), "employee"),
]


@dataclass
class EvalWorld:
  # repr=False：連線字串含密碼，pytest 失敗訊息或 traceback 不能印出來
  url: str = field(repr=False)
  qaUrl: str = field(repr=False)
  actors: dict[str, Actor]


def loadEnv() -> tuple[str, str]:
  load_dotenv(Path(__file__).resolve().parents[2] / ".env")
  testUrl = os.getenv("TEST_DATABASE_URL", "").strip()
  password = os.getenv("QA_DB_PASSWORD", "").strip()
  if not testUrl or not password:
    raise SystemExit("請先 docker compose up -d 啟動資料庫，並在 .env 設定 TEST_DATABASE_URL 與 QA_DB_PASSWORD，建立 qa_sandbox 帳號（見根目錄 README 的「問答」）")
  return testUrl, buildQaDatabaseUrl(testUrl, password)


def insertUser(conn, email: str, role: str, employeeId: int | None) -> Actor:
  # 評測不登入，密碼雜湊用假值；稽核紀錄的 user_id 有外鍵，所以要有真的使用者
  row = conn.execute(
    "INSERT INTO users (email, password_hash, role, employee_id) VALUES (%s, 'eval', %s, %s) RETURNING id",
    (email, role, employeeId),
  ).fetchone()
  return Actor(userId=row["id"], role=role, employeeId=employeeId)


def at(day: str, hour: int) -> datetime:
  return datetime.fromisoformat(f"{day}T{hour:02d}:00")


def buildOrg(conn, admin: Actor) -> tuple[dict[str, int], dict[str, Actor]]:
  root = orgService.createDepartment(conn, admin, "管理部")["id"]
  departments = {"管理部": root}
  for name in ("工程部", "業務部", "人資部"):
    departments[name] = orgService.createDepartment(conn, admin, name, root)["id"]
  ids: dict[str, int] = {}
  idsByNumber: dict[str, int] = {}
  actors: dict[str, Actor] = {}
  for number, name, department, title, managerNo, hiredOn, role in employeeRows:
    employeeId = orgService.createEmployee(conn, admin, {
      "employeeNo": number, "name": name, "departmentId": departments[department], "jobTitle": title,
      "managerId": idsByNumber[managerNo] if managerNo else None, "hiredOn": hiredOn,
    })["id"]
    ids[name] = employeeId
    idsByNumber[number] = employeeId
    actors[name] = insertUser(conn, f"{number.lower()}@eval.example.com", role, employeeId)
  return ids, actors


def buildShifts(conn, admin: Actor, ids: dict[str, int]) -> None:
  types = {row["code"]: row["id"] for row in conn.execute("SELECT id, code FROM shift_types").fetchall()}
  for code, name, start, end, breakStart, breakEnd in [
    ("early", "早班", "07:00", "16:00", "11:00", "12:00"),
    ("late", "晚班", "14:00", "23:00", "18:00", "19:00"),
    ("night", "大夜班", "22:00", "07:00", None, None),
  ]:
    types[code] = shiftService.createShiftType(conn, admin, {
      "code": code, "name": name, "startTime": start, "endTime": end, "breakStart": breakStart, "breakEnd": breakEnd,
    })["id"]
  # 沒有週班表的人走預設的標準班（週一到週五）；週班表沒列的星期幾是休息日
  rosterFrom = date(2026, 8, 1)
  for name, code, weekdays in [("黃志強", "late", range(5)), ("劉怡君", "early", range(5)), ("鄭家豪", "night", range(4))]:
    shiftService.createRoster(conn, admin, {
      "employeeId": ids[name], "effectiveFrom": rosterFrom,
      "days": [{"weekday": weekday, "shiftTypeId": types[code]} for weekday in weekdays],
    }, fixedNow)
  for name, day, code, note in [
    ("林小美", date(2026, 11, 18), None, "補休"),
    ("李佳穎", date(2026, 11, 21), "standard", "展場支援"),
    ("吳宗翰", date(2026, 11, 24), "early", "早班支援"),
  ]:
    shiftService.upsertOverride(conn, admin, {
      "employeeId": ids[name], "day": day, "shiftTypeId": types[code] if code else None, "note": note,
    }, fixedNow)
  # 過去的假日：沙盒區間內要有已經過去的假日，才問得出「上個月放過幾天假」
  orgService.upsertCalendarDay(conn, admin, date(2026, 10, 9), "holiday", "國慶日")
  orgService.upsertCalendarDay(conn, admin, date(2026, 11, 27), "holiday", "公司創立紀念日")
  orgService.upsertCalendarDay(conn, admin, date(2026, 12, 5), "makeup_workday", "補班日")


def buildBookings(conn, actors: dict[str, Actor], ids: dict[str, int]) -> None:
  admin = actors["admin"]
  resources = {}
  for name, kind, location, capacity in [
    ("A 會議室", "room", "3F", 8), ("B 會議室", "room", "5F", 4), ("投影機", "equipment", None, None), ("公務車", "vehicle", None, None),
  ]:
    resources[name] = bookingService.createResource(conn, admin, {"name": name, "kind": kind, "location": location, "capacity": capacity})["id"]
  bookings = {}
  # (標題, 分類, 主辦, 日期, 開始, 結束, 資源, 參加者)
  for title, category, organizer, day, start, end, resourceNames, attendees in [
    ("月會", "會議", "蔡明哲", "2026-11-09", 14, 15, ["A 會議室"], ["陳大文", "王建國", "張雅婷", "許淑芬", "林小美"]),
    ("工程部週會 11/10", "會議", "陳大文", "2026-11-10", 10, 11, ["A 會議室"], ["林小美", "劉怡君"]),
    ("業務週會 11/12", "會議", "王建國", "2026-11-12", 10, 11, ["B 會議室"], ["吳宗翰", "李佳穎"]),
    ("程式碼審查", "會議", "林小美", "2026-11-13", 14, 15, ["B 會議室"], ["陳大文", "黃志強", "劉怡君"]),
    ("工程部週會 11/17", "會議", "陳大文", "2026-11-17", 10, 11, ["A 會議室"], ["林小美", "劉怡君"]),
    ("專案啟動會", "會議", "林小美", "2026-11-17", 16, 17, ["A 會議室"], ["陳大文", "吳宗翰", "張雅婷"]),
    ("簡報彩排", "會議", "李佳穎", "2026-11-18", 13, 15, ["投影機"], ["吳宗翰"]),
    ("客戶拜訪", "外出", "吳宗翰", "2026-11-19", 9, 12, ["公務車"], []),
    ("需求訪談", "會議", "王建國", "2026-11-20", 14, 15, ["B 會議室", "投影機"], ["李佳穎", "林小美"]),
    ("預算討論", "會議", "王建國", "2026-11-20", 10, 11, ["A 會議室"], ["陳大文"]),
    ("工程部週會 11/24", "會議", "陳大文", "2026-11-24", 10, 11, ["A 會議室"], ["林小美", "劉怡君"]),
    ("季度檢討", "會議", "陳大文", "2026-11-24", 15, 17, ["A 會議室"], ["王建國", "張雅婷", "李佳穎"]),
    ("新人訓練", "訓練", "張雅婷", "2026-11-25", 9, 12, ["B 會議室", "投影機"], ["吳宗翰", "許淑芬"]),
    ("供應商拜訪", "外出", "張雅婷", "2026-11-26", 9, 12, ["公務車"], ["許淑芬"]),
    ("下週規劃", "會議", "陳大文", "2026-11-30", 15, 16, ["A 會議室"], ["王建國", "蔡明哲", "許淑芬"]),
    ("招募面談", "會議", "張雅婷", "2026-12-01", 10, 11, ["B 會議室"], ["陳大文", "吳宗翰"]),
  ]:
    created = bookingService.createBooking(conn, actors[organizer], BookingInput(
      title, category, at(day, start), at(day, end), [resources[name] for name in resourceNames],
      [ids[name] for name in attendees], acknowledgeWarnings=True,
    ))
    bookings[(title, day)] = created["id"]
  bookingService.cancelBooking(conn, actors["王建國"], bookings[("預算討論", "2026-11-20")])


def buildLeave(conn, actors: dict[str, Actor], ids: dict[str, int]) -> None:
  types = {row["code"]: row["id"] for row in conn.execute("SELECT id, code FROM leave_types").fetchall()}
  admin = actors["admin"]

  def request(name, code, start, end, reason):
    return leaveRequests.createRequest(conn, actors[name], LeaveInput(types[code], start, end, reason, acknowledgeWarnings=True), fixedNow)["id"]

  # 林小美：各種狀態與跨週末的多天請假（11-27 是公司假日，不算時數）
  approve = lambda requestId, approver: leaveRequests.approveRequest(conn, actors[approver], requestId, None, fixedNow)
  approve(request("林小美", "personal", at("2026-11-19", 9), at("2026-11-19", 18), "家裡有事"), "陳大文")
  request("林小美", "sick", at("2026-11-24", 13), at("2026-11-24", 18), "回診")
  approve(request("林小美", "annual", at("2026-11-26", 9), at("2026-11-30", 18), "出國旅遊"), "陳大文")
  withdrawn = request("林小美", "personal", at("2026-11-12", 9), at("2026-11-12", 12), "改期")
  leaveRequests.withdrawRequest(conn, actors["林小美"], withdrawn, fixedNow)
  # 黃志強今天晚班請病假：「現在誰在請假」會用到
  approve(request("黃志強", "sick", at("2026-11-17", 14), at("2026-11-17", 23), "發燒"), "陳大文")
  approve(request("劉怡君", "annual", at("2026-11-20", 7), at("2026-11-20", 16), "家庭旅遊"), "陳大文")
  rejected = request("吳宗翰", "personal", at("2026-11-23", 9), at("2026-11-23", 18), "私事")
  leaveRequests.rejectRequest(conn, actors["王建國"], rejected, "當天有客戶會議", fixedNow)
  cancelled = request("李佳穎", "annual", at("2026-12-01", 9), at("2026-12-01", 18), "休息")
  approve(cancelled, "王建國")
  leaveRequests.cancelRequest(conn, actors["李佳穎"], cancelled, fixedNow)
  approve(request("王建國", "annual", at("2026-10-05", 9), at("2026-10-05", 18), "陪家人"), "admin")
  # 不同時數的部分請假（2、4、6 小時）與多天請假，分散在各部門；其中兩筆落在上週
  approve(request("吳宗翰", "personal", at("2026-11-10", 9), at("2026-11-10", 11), "辦手續"), "王建國")
  approve(request("李佳穎", "personal", at("2026-11-12", 14), at("2026-11-12", 16), "銀行辦事"), "王建國")
  approve(request("劉怡君", "sick", at("2026-11-09", 7), at("2026-11-09", 11), "牙科"), "陳大文")
  approve(request("許淑芬", "sick", at("2026-11-13", 9), at("2026-11-13", 16), "感冒"), "蔡明哲")
  approve(request("陳大文", "annual", at("2026-11-02", 9), at("2026-11-04", 18), "家族旅行"), "蔡明哲")
  # 李佳穎也有一筆待核准的假
  request("李佳穎", "annual", at("2026-12-03", 9), at("2026-12-03", 18), "家人聚會")
  # 範圍外（沙盒從 2026-08-19 開始）
  approve(request("張雅婷", "personal", at("2026-06-01", 9), at("2026-06-01", 18), "搬家"), "admin")
  # 大夜班跨午夜的假，待核准
  request("鄭家豪", "sick", at("2026-11-18", 22), at("2026-11-19", 7), "看診")
  # 周志明先請假、之後離職：他的假仍在沙盒，但 employees 沒有他
  approve(request("周志明", "annual", at("2026-10-20", 9), at("2026-10-20", 18), "旅遊"), "王建國")
  orgService.updateEmployee(conn, admin, ids["周志明"], {"isActive": False, "leftOn": date(2026, 10, 31)})


def buildFixture(conn) -> dict[str, Actor]:
  admin = insertUser(conn, "admin@eval.example.com", "admin", None)
  ids, actors = buildOrg(conn, admin)
  actors["admin"] = admin
  buildShifts(conn, admin, ids)
  buildBookings(conn, actors, ids)
  buildLeave(conn, actors, ids)
  return {asker: actors[name] for asker, name in askerNames.items()}


@contextmanager
def openEvalWorld():
  testUrl, qaUrl = loadEnv()
  with temporarySchema(testUrl, "eval") as url:
    runMigrations(url, allModules)
    with openDb(url) as conn:
      actors = buildFixture(conn)
    yield EvalWorld(url=url, qaUrl=qaUrl, actors=actors)
