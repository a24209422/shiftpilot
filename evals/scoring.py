"""比對模型產生的 SQL 與標準答案 SQL 的執行結果。

比的是查詢結果而不是 SQL 文字：同一個問題可以有很多種寫法，結果相同就算對。
"""
from collections import Counter
from decimal import Decimal
from itertools import product


def normalizeValue(value):
  # COUNT 回傳整數、時數計算可能是浮點數或 Decimal（PostgreSQL 的 numeric），統一成四捨五入後的浮點數才比得起來
  if isinstance(value, (int, float, Decimal)):
    return round(float(value), 2)
  if isinstance(value, str):
    return value.strip()
  return value


def normalizeRows(rows):
  return [tuple(normalizeValue(value) for value in row) for row in rows]


def makeBag(items, compareAsSet):
  # 問「有誰」這類題目時，模型有沒有加 DISTINCT 都算對，所以改用集合；其他題目重複幾筆也要一致
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


def resultsMatch(goldRows, predictedRows, compareAsSet=False):
  gold, predicted = normalizeRows(goldRows), normalizeRows(predictedRows)
  if not gold or not predicted:
    return not gold and not predicted
  if not compareAsSet and len(gold) != len(predicted):
    return False
  goldBag = makeBag(gold, compareAsSet)
  # 模型常多選欄位（例如多帶出資源名稱），只要找得到一組欄位對應，讓資料列和標準答案完全相同就算對
  for mapping in product(*findColumnCandidates(gold, predicted, compareAsSet)):
    if len(set(mapping)) < len(mapping):
      continue
    projectedRows = (tuple(row[index] for index in mapping) for row in predicted)
    if makeBag(projectedRows, compareAsSet) == goldBag:
      return True
  return False
