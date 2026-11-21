import re

# 真正的防線是沙盒帳號沒有權限；這裡先擋掉明顯的寫入與危險函式，錯誤訊息也能回饋給模型修正
forbiddenKeywords = re.compile(
  r"\b(insert|update|delete|merge|truncate|drop|alter|create|grant|revoke|copy|vacuum|analyze|reindex|cluster|lock"
  r"|set|reset|do|call|execute|prepare|deallocate|discard|listen|notify|unlisten|comment|security|refresh|import|load|checkpoint"
  r"|into)\b",
  re.IGNORECASE,
)
# FOR UPDATE 會鎖列，FOR SHARE / FOR KEY SHARE 也會鎖列，都不該出現在唯讀查詢
forbiddenLocking = re.compile(r"\bfor\s+(no\s+key\s+update|share|key\s+share)\b", re.IGNORECASE)
# 底線是字元的一部分，\bset\b 擋不到 set_config，所以函式另外列；不要求後面接括號，避免 /**/ 或引號繞過
forbiddenFunctions = re.compile(
  r"\b(set_config|pg_read_file|pg_read_binary_file|pg_ls_dir|pg_stat_file|lo_\w+|dblink\w*"
  r"|pg_terminate_backend|pg_cancel_backend|pg_reload_conf|setval|nextval|currval|pg_notify|pg_sleep"
  r"|pg_advisory\w*|query_to_xml\w*|pg_ls_\w+|table_to_xml\w*|cursor_to_xml|database_to_xml\w*|schema_to_xml\w*)\b",
  re.IGNORECASE,
)
# dollar quoting 可以把整段內容藏進字串，檢查時看不到，所以直接不允許
dollarQuote = re.compile(r"\$\w*\$")


class UnsafeSqlError(ValueError):
  pass


def rejectUnicodeEscape(sql: str, quoteIndex: int) -> None:
  # U&"..." 與 U&'...' 會在解析時把 \XXXX 解碼成字元，檢查看到的是跳脫前的文字，所以直接拒絕
  # 這裡只在引號位於字串與註解之外時呼叫，所以字串內的 U& 文字不會被誤擋
  if quoteIndex < 2 or sql[quoteIndex - 1] != "&" or sql[quoteIndex - 2] not in "uU":
    return
  if quoteIndex < 3 or not (sql[quoteIndex - 3].isalnum() or sql[quoteIndex - 3] == "_"):
    raise UnsafeSqlError("不允許 Unicode 跳脫語法 U&")


def cleanSql(sql: str) -> str:
  # 逐字元掃描，讓字串與註解內的內容不影響後續檢查；引號識別字則還原成裸名稱，讓 "set_config" 仍被看見
  out = []
  i = 0
  n = len(sql)
  while i < n:
    if sql.startswith("--", i):
      end = sql.find("\n", i)
      i = n if end == -1 else end
      out.append(" ")
    elif sql.startswith("/*", i):
      # PostgreSQL 的區塊註解可以巢狀；這裡用非巢狀處理，只會讓更多文字暴露給檢查，方向是安全的
      end = sql.find("*/", i + 2)
      i = n if end == -1 else end + 2
      out.append(" ")
    elif sql[i] == "'":
      # E'...' 的反斜線跳脫會讓字串邊界判斷失準，直接拒絕以免藏住後面的指令
      if i > 0 and sql[i - 1] in "eE" and (i < 2 or not (sql[i - 2].isalnum() or sql[i - 2] == "_")):
        raise UnsafeSqlError("不允許 E 字串")
      rejectUnicodeEscape(sql, i)
      i += 1
      while i < n:
        if sql[i] == "'":
          if i + 1 < n and sql[i + 1] == "'":
            i += 2
            continue
          i += 1
          break
        i += 1
      out.append("''")
    elif sql[i] == '"':
      rejectUnicodeEscape(sql, i)
      i += 1
      name = []
      while i < n:
        if sql[i] == '"':
          if i + 1 < n and sql[i + 1] == '"':
            name.append('"')
            i += 2
            continue
          i += 1
          break
        name.append(sql[i])
        i += 1
      # 前後補空白，避免還原後的名稱和相鄰符號黏在一起
      out.append(" " + "".join(name) + " ")
    else:
      out.append(sql[i])
      i += 1
  return "".join(out)


def extractSql(text: str) -> str:
  # qwen3 這類推理模型會先輸出 <think> 區塊；沒有收尾的 <think> 代表後面都是推理過程，整段丟掉
  text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL)
  text = re.sub(r"<think>.*", "", text, flags=re.DOTALL)
  fenced = re.search(r"```(?:sql)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
  if fenced:
    text = fenced.group(1)
  else:
    # 小模型常不照格式，在 SQL 前面加說明文字，所以從第一個 SELECT / WITH 開始取；
    # 前面不能是英文字母或底線，但允許緊接在中文後面（例如「查詢如下SELECT」）
    start = re.search(r"(?<![A-Za-z_])(select|with)\b", text, flags=re.IGNORECASE)
    if start:
      text = text[start.start():]
  # 分號後面通常是模型補的解釋；只取第一句也順便擋掉多語句
  # 注意：這裡是字串層級的切割，字串常值裡的分號也會被切掉，這是已知的保守取捨
  return text.split(";")[0].strip()


def validateSql(sql: str) -> None:
  if not sql:
    raise UnsafeSqlError("模型沒有產生 SQL")
  if dollarQuote.search(sql):
    raise UnsafeSqlError("不允許 dollar quoting")
  # 之後所有檢查都只看 cleaned，字串與註解內容不會造成誤判，也無法藏住危險語句
  cleaned = cleanSql(sql)
  if not cleaned.strip():
    raise UnsafeSqlError("模型沒有產生 SQL")
  if not re.match(r"^\s*(select|with)\b", cleaned, re.IGNORECASE):
    raise UnsafeSqlError("只允許 SELECT 查詢")
  if ";" in cleaned:
    raise UnsafeSqlError("只允許單一 SQL 語句")
  if forbiddenKeywords.search(cleaned) or forbiddenLocking.search(cleaned) or forbiddenFunctions.search(cleaned):
    raise UnsafeSqlError("SQL 含有不允許的關鍵字或函式")
