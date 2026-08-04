"""PostgreSQL OCR 대기 행을 사이트별로 처리하는 DAG."""
import re

from airflow import DAG
from airflow.exceptions import AirflowSkipException
from airflow.operators.python import PythonOperator
from airflow.timetables.datasets import DatasetOrTimeSchedule
from airflow.timetables.interval import CronDataIntervalTimetable

from jobis_common import (
    DEFAULT_ARGS,
    JOB_POSTINGS_LOADED,
    POSTINGS_READY_FOR_RAG,
    SITES,
    START_DATE,
    ocr_task,
)


def publish_if_ocr_filled(**context) -> int:
    task_ids = [f"ocr_{site}" for site in SITES]
    summaries = context["ti"].xcom_pull(task_ids=task_ids) or []
    filled = 0
    for summary in summaries:
        match = re.search(r"\bfilled=(\d+)\b", str(summary or ""))
        if match:
            filled += int(match.group(1))
    if filled == 0:
        raise AirflowSkipException("이번 실행에서 OCR로 완료된 행이 없습니다.")
    print(f"[ocr_db] status=publish_rag_dataset filled={filled}", flush=True)
    return filled

with DAG(
    dag_id="jobis_ocr",
    description="PostgreSQL OCR 대기 행을 사이트별로 선점·처리하고 같은 행을 갱신",
    schedule=DatasetOrTimeSchedule(
        timetable=CronDataIntervalTimetable("*/30 * * * *", timezone="Asia/Seoul"),
        datasets=(JOB_POSTINGS_LOADED,),
    ),
    start_date=START_DATE,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    params={
        "ocr_max": 1,
        "ocr_max_attempts": 2,
        "ocr_retry_base_minutes": 60,
        "ocr_lease_minutes": 60,
    },
    tags=["jobis", "ocr"],
) as dag:
    ocrs = [ocr_task(site) for site in SITES]
    publish_ocr_result = PythonOperator(
        task_id="publish_ocr_result",
        python_callable=publish_if_ocr_filled,
        outlets=[POSTINGS_READY_FOR_RAG],
    )

    ocrs >> publish_ocr_result
