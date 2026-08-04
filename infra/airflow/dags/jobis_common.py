"""JOBIS Airflow DAG 사이에서 공유하는 데이터 계약과 태스크 팩토리."""
from __future__ import annotations

import os
from datetime import datetime, timedelta

from airflow.datasets import Dataset
from airflow.operators.bash import BashOperator
from airflow.providers.docker.operators.docker import DockerOperator
from docker.types import Mount

DATA_DIR = "/opt/jobis/DATA"
OCR_PYTHON = "/opt/jobis/ocr-venv/bin/python"
SITES = ("jobkorea", "saramin", "wanted", "incruit", "work24")
START_DATE = datetime(2026, 8, 1)
DEFAULT_ARGS = {"retries": 1, "retry_delay": timedelta(minutes=10)}

# Dataset 이벤트가 네 DAG의 성공 경계를 연결한다. URI는 실제 파일 경로가 아니라
# Airflow가 추적하는 논리적 데이터 자산 이름이다.
RAW_POSTINGS = Dataset("jobis://raw-site-postings")
JOB_POSTINGS_LOADED = Dataset("jobis://job-postings-loaded")
POSTINGS_READY_FOR_RAG = Dataset("jobis://postings-ready-for-rag")
RAG_INDEX_READY = Dataset("jobis://rag-index-ready")


def crawl_task(site: str) -> BashOperator:
    return BashOperator(
        task_id=f"crawl_{site}",
        bash_command=(
            f"cd {DATA_DIR} && python crawl_{site}_it.py "
            "--max-results 100000 --max-ocr-pending-results 200 "
            "--max-new {{ params.max_new }} "
            "--max-candidates {{ params.max_candidates }} "
            "--pages-per-keyword 2 --delay 1.0"
        ),
    )


def ocr_task(site: str) -> BashOperator:
    return BashOperator(
        task_id=f"ocr_{site}",
        bash_command=(
            f"cd {DATA_DIR} && {OCR_PYTHON} ocr_postgres.py --site {site} "
            "--engine paddle --max {{ params.ocr_max }} "
            "--max-attempts {{ params.ocr_max_attempts }} "
            "--retry-base-minutes {{ params.ocr_retry_base_minutes }} "
            "--lease-minutes {{ params.ocr_lease_minutes }}"
        ),
        pool="ocr_pool",
        do_xcom_push=True,
    )


def load_postgres_task() -> BashOperator:
    return BashOperator(
        task_id="load_job_postings",
        bash_command=(
            f"cd {DATA_DIR} && python export_postgres.py --from-source-jsons && "
            'psql "$JOBRAG_PG_DSN" -v ON_ERROR_STOP=1 '
            "-f exports/all_job_postings_postgres.sql"
        ),
        outlets=[JOB_POSTINGS_LOADED, POSTINGS_READY_FOR_RAG],
    )


def export_rag_postings_task() -> BashOperator:
    return BashOperator(
        task_id="export_rag_postings",
        bash_command=f"cd {DATA_DIR} && python export_rag_postgres.py",
    )


def rag_ingest_task() -> DockerOperator:
    return DockerOperator(
        task_id="rag_ingest",
        image="jobis/rag-ingest:latest",
        command=[
            "bash",
            "-c",
            "python run_ingest_additive.py /exports/all_job_postings_rag.json",
        ],
        environment={
            "PG_DSN": os.environ.get("JOBRAG_PG_DSN", ""),
            "HF_HOME": "/hf",
        },
        mounts=[
            Mount(
                source="jobis-crawl-exports",
                target="/exports",
                type="volume",
                read_only=True,
            ),
            Mount(source="jobis-hf-cache", target="/hf", type="volume"),
        ],
        network_mode="jobis-net",
        docker_url="unix://var/run/docker.sock",
        auto_remove="success",
        mount_tmp_dir=False,
        outlets=[RAG_INDEX_READY],
    )
