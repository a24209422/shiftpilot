# Task 4 報告
狀態：DONE
- 新增 backend/app/modules/qa/sandbox.py、tests/qa/test_sandbox_data.py、tests/qa/test_sandbox_security.py，內容與 brief 逐字相同。
- 已對照真實 schema 與函式（resolveRange、workWindows、clipWindows、ResolvedDay、isLeaveManager、各表欄位）：列為 dict、欄位名、順序皆符合，無需修改實作或測試。
- 對抗測試全數 fail-closed，沒有放寬或跳過任何一項。
- 測試：tests/qa/test_sandbox_*.py 31 passed（137 秒）；tests/qa 其餘 80 passed。
- 未單獨觀察紅燈階段（實作與測試同時寫入），模組不存在時的 ModuleNotFoundError 為必然結果。

## Fix round 1
- I1：02-create-qa-user.sh 加上 ALTER ROLE qa_sandbox SET track_activities/track_counts = off（冪等、已存在角色也套用）；README 補說明。已對開發資料庫重跑 `docker compose exec -T postgres sh /docker-entrypoint-initdb.d/02-create-qa-user.sh`，pg_db_role_setting 確認為 {track_activities=off,track_counts=off}。測試 testOtherAskersQueriesAreNotVisible（含 n_tup_ins 檢查）。
- I2：runQuery 包在 `conn.transaction(force_rollback=True)`；測試 testSessionSettingsAreRevertedBetweenQueries（唯讀、GRANT/INSERT、pg_sleep(6.5) 約 5 秒被取消）。sqlguard 已禁止 pg_cancel_backend、pg_terminate_backend、pg_advisory*，不需補；程式碼註解已說明。
- I3：具名伺服器端游標 + fetchmany(maxRows+1)；testCrossJoinIsCappedInDatabase（三表交叉連接，約 0.1 秒）。註：具名游標只能跑 SELECT/VALUES，其他陳述式會報錯（本來就不該放行）。
- M1：建表、COPY、REVOKE 放同一交易，之後才 SET。
- M3：jsonValue 遞迴處理 list/tuple/dict，bytes 轉十六進位，UUID 轉字串；testJsonValuesAreNestedAndBinarySafe。
- M4：testPublicTablesAreNotGranted（public 內每張表 has_table_privilege 為 false）。
- 指令：`cd backend; python -m pytest tests/qa -q` -> 116 passed in 89s。（有一次全跑時 CrossJoin 測試因機器負載超過 3 秒，單獨與再跑皆通過，約 0.1 秒。）
