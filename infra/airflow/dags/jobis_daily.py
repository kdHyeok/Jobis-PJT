"""JOBIS 일일 수집 -> PostgreSQL 적재 DAG.

DATA/run_daily_update.py의 무인 실행 장치는 Airflow 기본 기능으로 대체한다:
  잠금 파일 -> max_active_runs=1 / 로그 파일 -> 태스크 로그 /
  부분 실패 허용 -> trigger_rule / 재시도 -> retries.
크롤·병합·적재 스크립트는 DATA/ 원본을 그대로 호출한다 (수정 없음).

흐름:  crawl x5 (병렬) -> merge -> [load_job_postings, rag_ingest]
  - load_job_postings: export_postgres.py 생성 SQL을 psql로 적재 (job_postings 테이블)
  - rag_ingest: RAG 이미지(run_ingest_additive.py)로 postings/chunks 벡터 적재.
    가산(additive) 적재라 기존 공고를 비활성화하지 않는다 — 한 사이트 크롤이
    실패한 날에도 안전하다.

OCR(enrich_ocr.py, paddle)은 이미지가 준비되면 crawl과 merge 사이에 사이트별
태스크로 추가한다. 그전까지 need_ocr='O' 공고는 본문 없이 적재되고 RAG 색인에서
제외된다 (jobrag/sources.py 정책).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.providers.docker.operators.docker import DockerOperator
from docker.types import Mount

DATA_DIR = "/opt/jobis/DATA"
SITES = ("jobkorea", "saramin", "wanted", "incruit", "work24")

with DAG(
    dag_id="jobis_daily_ingest",
    schedule="0 3 * * *",  # KST 03:00 (AIRFLOW__CORE__DEFAULT_TIMEZONE=Asia/Seoul)
    start_date=datetime(2026, 8, 1),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 1, "retry_delay": timedelta(minutes=10)},
    params={"max_new": 50},
) as dag:
    crawls = [
        BashOperator(
            task_id=f"crawl_{site}",
            bash_command=(
                f"cd {DATA_DIR} && python crawl_{site}_it.py "
                "--max-results 100000 --max-ocr-pending-results 200 "
                "--max-new {{ params.max_new }} --pages-per-keyword 2 --delay 1.0"
            ),
        )
        for site in SITES
    ]

    # 일부 사이트가 실패해도 성공한 수집분으로 병합은 진행한다 (run_daily_update.py 정책).
    merge = BashOperator(
        task_id="merge",
        bash_command=f"cd {DATA_DIR} && python merge_job_postings.py",
        trigger_rule="all_done",
    )

    load_job_postings = BashOperator(
        task_id="load_job_postings",
        bash_command=(
            f"cd {DATA_DIR} && python export_postgres.py && "
            'psql "$JOBRAG_PG_DSN" -v ON_ERROR_STOP=1 '
            "-f exports/all_job_postings_postgres.sql"
        ),
    )

    rag_ingest = DockerOperator(
        task_id="rag_ingest",
        image="jobis/rag-ingest:latest",
        command=[
            "bash", "-c",
            'psql "$PG_DSN" -v ON_ERROR_STOP=1 -f schema.sql && '
            "python run_ingest_additive.py /exports/all_job_postings.json",
        ],
        environment={
            "PG_DSN": os.environ.get("JOBRAG_PG_DSN", ""),
            "HF_HOME": "/hf",
        },
        mounts=[
            Mount(source="jobis-crawl-exports", target="/exports", type="volume", read_only=True),
            Mount(source="jobis-hf-cache", target="/hf", type="volume"),
        ],
        network_mode="jobis-net",
        docker_url="unix://var/run/docker.sock",
        auto_remove="success",
        mount_tmp_dir=False,
    )

    crawls >> merge >> [load_job_postings, rag_ingest]
