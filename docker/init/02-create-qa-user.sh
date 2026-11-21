#!/bin/sh
# 建立問答沙盒專用的登入帳號。第一次啟動資料庫時自動執行；現有的資料庫照 README 手動執行一次，重複執行不會出錯
# postgres 的 entrypoint 是用 source 的方式跑這個檔案：不能用 exit（會中斷整個初始化），也不開 set -e（會留在 entrypoint 的 shell 裡）
createQaSandboxRole() {
  if [ -z "$QA_DB_PASSWORD" ]; then
    echo "沒有設定 QA_DB_PASSWORD，略過建立 qa_sandbox（問答功能會停用）"
    return 0
  fi
  psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER:-postgres}" --dbname postgres -v qaPassword="$QA_DB_PASSWORD" <<'EOSQL'
-- 只能登入與建暫存表：不給任何資料表權限、不加入任何角色，模型的 SQL 才沒有角色可以切換
SELECT format('CREATE ROLE qa_sandbox LOGIN NOINHERIT PASSWORD %L', :'qaPassword')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'qa_sandbox') \gexec
-- 所有沙盒連線共用同一個角色：關掉活動追蹤，pg_stat_activity 才不會讓別人看到其他提問者的 SQL（已存在的角色也要套用）
ALTER ROLE qa_sandbox SET track_activities = off;
ALTER ROLE qa_sandbox SET track_counts = off;
EOSQL
}

createQaSandboxRole
