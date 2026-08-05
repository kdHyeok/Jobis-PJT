"""적재가 끝난 canonical 공고를 RAG 벡터 인덱스로 반영하는 DAG."""
from airflow import DAG

from jobis_common import (
    DEFAULT_ARGS,
    POSTINGS_READY_FOR_RAG,
    START_DATE,
    export_rag_postings_task,
    rag_ingest_task,
)

with DAG(
    dag_id="jobis_rag",
    description="신규·변경 공고 청크를 선택한 임베딩 provider로 pgvector에 적재",
    schedule=[POSTINGS_READY_FOR_RAG],
    start_date=START_DATE,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["jobis", "rag"],
) as dag:
    export_rag_postings = export_rag_postings_task()
    rag_ingest = rag_ingest_task()

    export_rag_postings >> rag_ingest
