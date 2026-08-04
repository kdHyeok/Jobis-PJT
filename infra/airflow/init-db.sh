#!/bin/bash
# pgdata 볼륨이 비어 있을 때(최초 기동) 한 번만 실행된다.
# airflow 메타 DB와 jobrag 데이터 DB를 만들고, jobrag에 pgvector 확장을 설치한다.
# jobrag 테이블은 DB 생성 뒤 jobrag-migrate(Flyway)가 버전 순서대로 만든다.
set -euo pipefail

JOBRAG_DB_NAME="${JOBRAG_DB_NAME:-jobrag}"
if [[ ! "$JOBRAG_DB_NAME" =~ ^[a-z][a-z0-9_]{0,62}$ ]]; then
    echo "invalid JOBRAG_DB_NAME: $JOBRAG_DB_NAME" >&2
    exit 1
fi

psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -v jobrag_db_name="$JOBRAG_DB_NAME" <<-EOSQL
    CREATE USER airflow PASSWORD '${AIRFLOW_DB_PASSWORD}';
    CREATE DATABASE airflow OWNER airflow;
    CREATE USER jobrag PASSWORD '${JOBRAG_DB_PASSWORD}';
    CREATE DATABASE :"jobrag_db_name" OWNER jobrag;
EOSQL

psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$JOBRAG_DB_NAME" \
    -c "CREATE EXTENSION IF NOT EXISTS vector;"
