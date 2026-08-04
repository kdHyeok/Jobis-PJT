"""매일 사이트별 원본 채용공고를 수집하는 DAG."""
from airflow import DAG
from airflow.operators.empty import EmptyOperator

from jobis_common import DEFAULT_ARGS, RAW_POSTINGS, SITES, START_DATE, crawl_task

with DAG(
    dag_id="jobis_collect",
    description="사이트 5곳의 원본 채용공고를 병렬 수집",
    schedule="0 3 * * *",
    start_date=START_DATE,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    params={"max_new": 50, "max_candidates": 200},
    tags=["jobis", "collect"],
) as dag:
    crawls = [crawl_task(site) for site in SITES]

    # 일부 사이트가 실패해도 기존 정책대로 성공한 사이트의 원본을 다음 단계에 전달한다.
    publish_raw_postings = EmptyOperator(
        task_id="publish_raw_postings",
        trigger_rule="all_done",
        outlets=[RAW_POSTINGS],
    )

    crawls >> publish_raw_postings
