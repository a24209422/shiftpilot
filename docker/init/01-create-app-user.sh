#!/bin/sh
# PostgreSQL 容器只在資料目錄是空的（第一次啟動）時執行這支 script
set -e

# app 不用 superuser 連線：text2sql 執行的是模型寫的 SQL，superuser 可以用 pg_read_file() 這類函式讀伺服器上的檔案
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres -v appPassword="$APP_DB_PASSWORD" <<'EOSQL'
CREATE ROLE schedule_app LOGIN PASSWORD :'appPassword';
CREATE DATABASE schedule OWNER schedule_app;
-- 測試與評測另開一個資料庫，跑測試時不會碰到 app 的資料
CREATE DATABASE schedule_test OWNER schedule_app;
EOSQL
