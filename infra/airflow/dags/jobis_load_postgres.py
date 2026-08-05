"""canonical 공고를 PostgreSQL job_postings에 UPSERT하는 DAG."""
from airflow import DAG

from jobis_common import (
    DEFAULT_ARGS,
    RAW_POSTINGS,
    START_DATE,
    load_postgres_task,
)

with DAG(
    dag_id="jobis_load_postgres",
    description="사이트별 수집 원본의 완료/OCR 대기 공고를 PostgreSQL에 선적재",
    schedule=[RAW_POSTINGS],
    start_date=START_DATE,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["jobis", "load"],
) as dag:
    load_postgres_task()
