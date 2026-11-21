"""比對模型 SQL 與標準答案 SQL 的執行結果。

比的是查詢結果而不是 SQL 文字：同一個問題可以有很多種寫法，結果相同就算對。
"""
import hashlib
import json
from collections import Counter
from decimal import Decimal
from itertools import product


def normalizeValue(value):
  # COUNT 是整數、時數可能是浮點數或 numeric，統一成四捨五入後的浮點數才比得起來；bool 是 int 的子類別，要先排除
  if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
    return round(float(value), 2)
  if isinstance(value, str):
    return value.strip()
  # array_agg、json_agg 等會回傳 list 或 dict，它們不能放進 Counter 或 set；轉成 tuple 才能比對，遞迴處理是因為內層還可能有數字或字串
  if isinstance(value, (list, tuple)):
    return tuple(normalizeValue(item) for item in value)
  if isinstance(value, dict):
    # 依 key 排序，讓 JSON 物件的鍵順序不同也視為相同；key 本身只看字串形式，避免混合型別排序出錯
    return tuple(sorted(((key, normalizeValue(item)) for key, item in value.items()), key=lambda pair: str(pair[0])))
  return value


def normalizeRows(rows) -> list[tuple]:
  return [tuple(normalizeValue(value) for value in row) for row in rows]


def makeBag(items, compareAsSet):
  # 問「有誰」時，模型有沒有加 DISTINCT 都算對，所以改用集合；其他題目重複幾筆也要一致
  return set(items) if compareAsSet else Counter(items)


def findColumnCandidates(goldRows, predictedRows, compareAsSet):
  """標準答案的每個欄位，可能對應到模型結果的哪幾個欄位。"""
  candidates = []
  for goldIndex in range(len(goldRows[0])):
    goldColumn = makeBag((row[goldIndex] for row in goldRows), compareAsSet)
    candidates.append([
      predictedIndex for predictedIndex in range(len(predictedRows[0]))
      if makeBag((row[predictedIndex] for row in predictedRows), compareAsSet) == goldColumn
    ])
  return candidates


def resultsMatch(goldRows, predictedRows, compareAsSet=False) -> bool:
  gold, predicted = normalizeRows(goldRows), normalizeRows(predictedRows)
  if not gold or not predicted:
    return not gold and not predicted
  if not compareAsSet and len(gold) != len(predicted):
    return False
  goldBag = makeBag(gold, compareAsSet)
  # 模型常多選欄位（例如多帶出部門），只要找得到一組欄位對應，讓資料列和標準答案完全相同就算對
  for mapping in product(*findColumnCandidates(gold, predicted, compareAsSet)):
    if len(set(mapping)) < len(mapping):
      continue
    projectedRows = (tuple(row[index] for index in mapping) for row in predicted)
    if makeBag(projectedRows, compareAsSet) == goldBag:
      return True
  return False


def resultHash(rowsList) -> str:
  # 排序後再 hash：快照只在乎答案的內容，資料庫回傳順序改變不該被當成答案改變
  canonical = [sorted(json.dumps(list(row), ensure_ascii=False, default=str) for row in normalizeRows(rows)) for rows in rowsList]
  return hashlib.sha256(json.dumps(canonical, ensure_ascii=False).encode("utf-8")).hexdigest()
