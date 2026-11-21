import re

# 真正的防線是沙盒帳號沒有權限；這裡先擋掉明顯的寫入與危險函式，錯誤訊息也能回饋給模型修正
forbiddenKeywords = re.compile(
  r"\b(insert|update|delete|merge|truncate|drop|alter|create|grant|revoke|copy|vacuum|analyze|reindex|cluster|lock"
  r"|set|reset|do|call|execute|prepare|deallocate|discard|listen|notify|unlisten|comment|security|refresh|import|load|checkpoint)\b",
  re.IGNORECASE,
)
# 底線是字元的一部分，\bset\b 擋不到 set_config，所以函式另外列
forbiddenFunctions = re.compile(
  r"\b(set_config|pg_read_file|pg_read_binary_file|pg_ls_dir|pg_stat_file|lo_import|lo_export|lo_\w+|dblink\w*"
  r"|pg_terminate_backend|pg_cancel_backend|pg_reload_conf)\s*\(",
  re.IGNORECASE,
)


class UnsafeSqlError(ValueError):
  pass


def extractSql(text: str) -> str:
  # qwen3 這類推理模型會先輸出 <think> 區塊
  text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL)
  fenced = re.search(r"```(?:sql)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
  if fenced:
    text = fenced.group(1)
  else:
    # 小模型常不照格式，在 SQL 前面加說明文字，所以從第一個 SELECT / WITH 開始取
    start = re.search(r"\b(select|with)\b", text, flags=re.IGNORECASE)
    if start:
      text = text[start.start():]
  # 分號後面通常是模型補的解釋；只取第一句也順便擋掉多語句
  return text.split(";")[0].strip()


def validateSql(sql: str) -> None:
  if not sql:
    raise UnsafeSqlError("模型沒有產生 SQL")
  if not re.match(r"^\s*(select|with)\b", sql, re.IGNORECASE):
    raise UnsafeSqlError("只允許 SELECT 查詢")
  if ";" in sql:
    raise UnsafeSqlError("只允許單一 SQL 語句")
  if forbiddenKeywords.search(sql) or forbiddenFunctions.search(sql):
    raise UnsafeSqlError("SQL 含有不允許的關鍵字或函式")
