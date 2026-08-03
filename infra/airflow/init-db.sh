#!/bin/bash
# pgdata 볼륨이 비어 있을 때(최초 기동) 한 번만 실행된다.
# airflow 메타 DB와 jobrag 데이터 DB를 만들고, jobrag에 pgvector 확장을 설치한다.
# RAG 테이블(postings/chunks)은 rag_ingest 태스크가 schema.sql로 스스로 만든다.
set -euo pipefail

psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" <<-EOSQL
    CREATE USER airflow PASSWORD '${AIRFLOW_DB_PASSWORD}';
    CREATE DATABASE airflow OWNER airflow;
    CREATE USER jobrag PASSWORD '${JOBRAG_DB_PASSWORD}';
    CREATE DATABASE jobrag OWNER jobrag;
EOSQL

psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d jobrag \
    -c "CREATE EXTENSION IF NOT EXISTS vector;"
