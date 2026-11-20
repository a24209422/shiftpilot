"""執行標準答案 SQL。

失敗時只回報題號：psycopg 的錯誤訊息會帶出 SQL 原文，test 題的 SQL 不能因為標準答案出錯而被印出來。
"""
import psycopg

import db


class GoldSqlError(Exception):
  def __init__(self, caseIds):
    super().__init__(f"標準答案執行失敗，題號：{', '.join(caseIds)}")
    self.caseIds = caseIds


def runGoldSql(databaseUrl, caseId, sql):
  try:
    return db.runReadOnlyQuery(databaseUrl, sql)[1]
  except psycopg.Error:
    # from None：不帶原本的例外，否則 traceback 照樣會印出 SQL
    raise GoldSqlError([caseId]) from None
