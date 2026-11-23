"""dev 每題「Jev 選了哪個工具還答得對」。

依過去 dev 的 agent、jev 紀錄中只用一個工具就答對過的工具定出來。
s02 用 find_available_people 答對過，但那個工具不知道班別，只是剛好名單相同，所以不列。
只放 dev：test 題的標籤不能出現在這裡，否則就等於看過 test 題。
"""

runSqlOnly = frozenset({"run_sql"})

acceptableTools: dict[str, frozenset[str]] = {
  **{caseId: runSqlOnly for caseId in (
    "o01", "o02", "o03", "o04", "o05",
    "s01", "s02", "s03", "s04", "s05", "s06", "s07", "s08",
    "a06",
    "l01", "l02", "l03", "l04", "l05", "l06", "l07", "l08",
    "m02", "m03", "m04", "m05", "m06",
    "g01", "g02", "g03", "g04", "g05",
  )},
  "a01": frozenset({"find_available_people"}),
  "a07": frozenset({"find_available_people"}),
  "a03": frozenset({"get_busy_periods"}),
  "a04": frozenset({"get_busy_periods"}),
  "a05": frozenset({"get_busy_periods"}),
  "m07": frozenset({"get_busy_periods"}),
  "a02": frozenset({"get_busy_periods", "run_sql"}),
  "m01": frozenset({"get_busy_periods", "run_sql"}),
}
