import argparse
import getpass
import sys
from datetime import date, datetime, time, timedelta

import psycopg

from app.config import loadConfig, loadEnvFile
from app.infra.actor import Actor
from app.infra.db import openDb
from app.infra.errors import AppError
from app.infra.migrate import runMigrations
from app.modules import allModules
from app.modules.booking import service as bookingService
from app.modules.booking.service import BookingInput
from app.modules.core import service as coreService
from app.modules.org import service as orgService

roleChoices = ["employee", "manager", "hr", "admin"]


def migrateCommand(databaseUrl: str) -> list[str]:
  applied = runMigrations(databaseUrl, allModules)
  for item in applied:
    print(f"已套用 {item}")
  if not applied:
    print("沒有新的遷移")
  return applied


def createUserCommand(databaseUrl: str, email: str, role: str, password: str, employeeNo: str | None = None) -> int:
  with openDb(databaseUrl) as conn:
    employeeId = None
    if employeeNo:
      row = conn.execute("SELECT id FROM employees WHERE employee_no = %s", (employeeNo,)).fetchone()
      if row is None:
        raise AppError("NOT_FOUND", f"找不到員工編號 {employeeNo}", 404)
      employeeId = row["id"]
    # actor 是 None：這時候還沒有任何帳號可以當作操作者，稽核紀錄的 user_id 會是空的
    user = coreService.createUser(conn, None, email, password, role, employeeId)
  return user["id"]


def seedDemoCommand(databaseUrl: str) -> None:
  with openDb(databaseUrl) as conn:
    if conn.execute("SELECT 1 FROM employees LIMIT 1").fetchone() is not None:
      raise AppError("NOT_EMPTY", "資料庫已經有員工資料，不覆寫：示範資料只用在空的開發資料庫", 409)
    admin = conn.execute("SELECT id FROM users WHERE role = 'admin' AND is_active ORDER BY id LIMIT 1").fetchone()
    if admin is None:
      # 排程的建立者（created_by）一定要是真的帳號；示範資料不自己建立帳號，所以要先有管理員
      raise AppError("NO_ADMIN", "示範排程需要一個建立者：請先用 createUser 建立管理員", 409)
    actor = Actor(userId=admin["id"], role="admin", employeeId=None)

    departments = {name: orgService.createDepartment(conn, actor, name)["id"] for name in ("工程部", "業務部", "人資部")}

    def addEmployee(number, name, department, title, managerId, hiredOn):
      data = {"employeeNo": number, "name": name, "departmentId": departments[department], "jobTitle": title, "managerId": managerId, "hiredOn": hiredOn}
      return orgService.createEmployee(conn, actor, data)["id"]

    chen = addEmployee("E001", "陳大文", "工程部", "工程部經理", None, date(2020, 3, 1))
    lin = addEmployee("E002", "林小美", "工程部", "資深工程師", chen, date(2021, 7, 15))
    huang = addEmployee("E003", "黃志強", "業務部", "業務專員", lin, date(2023, 2, 1))
    chang = addEmployee("E004", "張雅婷", "人資部", "人資專員", chen, date(2022, 9, 1))

    def addResource(**data):
      return bookingService.createResource(conn, actor, data)["id"]

    bigRoom = addResource(name="3F 大會議室", kind="room", location="3 樓", capacity=12, features=["video", "whiteboard"])
    smallRoom = addResource(name="2F 小會議室", kind="room", location="2 樓", capacity=4, features=["whiteboard"])
    projector = addResource(name="可攜式投影機", kind="equipment", features=["hdmi"])
    car = addResource(name="公務車（白色）", kind="vehicle", note="出車前請填里程")

    # 排在「本週」與「下週」，每次建立都看得到有東西
    monday = datetime.combine(date.today() - timedelta(days=date.today().weekday()), time.min)

    def book(dayOffset, hour, hours, title, category, resourceIds, organizerId, attendeeIds):
      startAt = monday + timedelta(days=dayOffset, hours=hour)
      data = BookingInput(
        title, category, startAt, startAt + timedelta(hours=hours), resourceIds, attendeeIds,
        organizerEmployeeId=organizerId, acknowledgeWarnings=True,
      )
      bookingService.createBooking(conn, actor, data)

    book(0, 10, 1, "團隊週會", "會議", [bigRoom], chen, [lin, huang])
    book(1, 14, 1.5, "客戶簡報", "簡報", [bigRoom, projector], huang, [chen])
    book(2, 9.5, 1, "一對一面談", "面談", [smallRoom], chen, [lin])
    book(3, 13, 4, "客戶拜訪", "外出", [car], huang, [])
    book(7, 10, 1, "團隊週會", "會議", [bigRoom], chen, [lin, huang])
    book(8, 15, 1, "面試", "面談", [smallRoom], chang, [lin])


def buildParser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(prog="python -m app.cli", description="請假排班系統的管理指令（在 backend/ 目錄執行）")
  commands = parser.add_subparsers(dest="command", required=True)
  commands.add_parser("migrate", help="套用還沒執行過的資料庫遷移")
  createUser = commands.add_parser("createUser", help="建立帳號（密碼會用互動方式輸入兩次，不能放在命令列參數）")
  createUser.add_argument("--email", required=True)
  createUser.add_argument("--role", required=True, choices=roleChoices)
  createUser.add_argument("--employee-no", dest="employeeNo", help="連到這個員工編號的員工")
  commands.add_parser("seedDemo", help="寫入示範資料（只能用在沒有員工的開發資料庫）")
  return parser


def askPassword() -> str | None:
  # 不接受命令列參數：命令列會留在 shell 歷史與程序清單裡
  first = getpass.getpass("密碼：")
  if first != getpass.getpass("再輸入一次密碼："):
    print("兩次輸入的密碼不一樣", file=sys.stderr)
    return None
  return first


def main(argv: list[str] | None = None) -> int:
  loadEnvFile()
  args = buildParser().parse_args(argv)
  try:
    databaseUrl = loadConfig().databaseUrl
    if args.command == "migrate":
      migrateCommand(databaseUrl)
    elif args.command == "createUser":
      password = askPassword()
      if password is None:
        return 1
      userId = createUserCommand(databaseUrl, args.email, args.role, password, args.employeeNo)
      print(f"已建立帳號，id = {userId}")
    elif args.command == "seedDemo":
      seedDemoCommand(databaseUrl)
      print("已寫入示範資料")
  except AppError as error:
    print(f"錯誤：{error.message}", file=sys.stderr)
    return 1
  except RuntimeError as error:
    print(f"錯誤：{error}", file=sys.stderr)
    return 1
  except psycopg.OperationalError as error:
    print(f"連不上資料庫（有執行 docker compose up -d 嗎？）：{error}", file=sys.stderr)
    return 1
  return 0


if __name__ == "__main__":
  sys.exit(main())
