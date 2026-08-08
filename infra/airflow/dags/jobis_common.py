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


class _CpuQuotaApiClient:
    """Delegate Docker API calls while adding a hard CPU quota to HostConfig."""

    def __init__(self, client, cpus: float):
        self._client = client
        self._cpus = cpus

    def __getattr__(self, name):
        return getattr(self._client, name)

    def create_host_config(self, *args, **kwargs):
        # CFS uses a 100 ms period; quota 200000 therefore means at most 2 CPUs.
        kwargs["cpu_period"] = 100_000
        kwargs["cpu_quota"] = round(self._cpus * 100_000)
        return self._client.create_host_config(*args, **kwargs)


class CpuLimitedDockerOperator(DockerOperator):
    """DockerOperator with both CPU shares and an enforceable CFS quota."""

    def __init__(self, *, hard_cpus: float, **kwargs):
        if hard_cpus <= 0:
            raise ValueError("hard_cpus must be greater than zero")
        self.hard_cpus = hard_cpus
        super().__init__(cpus=hard_cpus, **kwargs)

    @property
    def cli(self):
        return _CpuQuotaApiClient(self.hook.api_client, self.hard_cpus)


def _rag_model_environment() -> dict[str, str]:
    """Pass the scheduler's non-secret RAG model selection to DockerOperator."""

    defaults = {
        "RAG_EMBED_PROVIDER": "local",
        "RAG_LOCAL_EMBED_MODEL": "BAAI/bge-m3",
        "RAG_GMS_EMBED_MODEL": "text-embedding-3-large",
        "RAG_VECTOR_DIMENSIONS": "1024",
        "RAG_RERANK_PROVIDER": "local",
        "RAG_LOCAL_RERANK_MODEL": "BAAI/bge-reranker-v2-m3",
        "RAG_GMS_RERANK_MODEL": "gpt-4.1-mini",
        "RAG_LOCAL_CPU_THREADS": "2",
        "RAG_INGEST_CPUS": "2.0",
        "RAG_EMBED_BATCH_SIZE": "8",
        "RAG_INGEST_WINDOW_SIZE": "64",
        "RAG_LOCAL_RERANK_BATCH_SIZE": "4",
        "RAG_GMS_OPENAI_BASE_URL": (
            "https://gms.ssafy.io/gmsapi/api.openai.com/v1"
        ),
        "RAG_GMS_TIMEOUT_SECONDS": "60",
        "RAG_GMS_MAX_RETRIES": "2",
        "RAG_GMS_RERANK_BATCH_SIZE": "30",
        "RAG_GMS_RERANK_MAX_CHARS": "1800",
    }
    environment = {key: os.environ.get(key, value) for key, value in defaults.items()}
    for override in ("RAG_EMBED_MODEL", "RAG_RERANK_MODEL"):
        if os.environ.get(override):
            environment[override] = os.environ[override]
    return environment


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
        # OCR 과 RAG 적재가 동시에 돌면 메모리가 소진된다(2026-08-06 장애).
        # 둘을 같은 단일 슬롯 풀에 넣어 직렬화한다.
        pool="heavy_memory_pool",
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


def rag_ingest_task() -> CpuLimitedDockerOperator:
    environment = _rag_model_environment()
    threads = environment["RAG_LOCAL_CPU_THREADS"]
    environment.update(
        {
            "PG_DSN": os.environ.get("JOBRAG_PG_DSN", ""),
            "HF_HOME": "/hf",
            "OMP_NUM_THREADS": threads,
            "MKL_NUM_THREADS": threads,
            "OPENBLAS_NUM_THREADS": threads,
            "NUMEXPR_NUM_THREADS": threads,
            "RAYON_NUM_THREADS": threads,
            "TOKENIZERS_PARALLELISM": "false",
        }
    )
    ingest_cpus = float(environment["RAG_INGEST_CPUS"])
    if ingest_cpus <= 0:
        raise ValueError("RAG_INGEST_CPUS must be greater than zero")
    return CpuLimitedDockerOperator(
        task_id="rag_ingest",
        image=os.environ.get("RAG_INGEST_IMAGE", "jobis/rag-ingest:latest"),
        command=[
            "bash",
            "-c",
            "python run_ingest_additive.py /exports/all_job_postings_rag.json",
        ],
        environment=environment,
        private_environment={"GMS_KEY": os.environ.get("GMS_KEY", "")},
        hard_cpus=ingest_cpus,
        # 적재는 청크 벡터를 모두 메모리에 모은 뒤 한 번에 커밋한다. 2026-08-06 에는
        # 7.1GB 까지 자라 호스트 전체 메모리를 소진시켰다. 상한을 두면 이 컨테이너만
        # 종료되고 태스크가 실패로 남는다 — 서버는 영향을 받지 않는다.
        mem_limit=os.environ.get("RAG_INGEST_MEM_LIMIT", "4g"),
        pool="heavy_memory_pool",
        mounts=[
            Mount(
                source="jobis-crawl-exports",
                target="/exports",
                type="volume",
                read_only=True,
            ),
            Mount(source="jobis-hf-cache", target="/hf", type="volume"),
        ],
        network_mode=os.environ.get("RAG_DOCKER_NETWORK_MODE", "jobis-net"),
        docker_url="unix://var/run/docker.sock",
        auto_remove="success",
        mount_tmp_dir=False,
        outlets=[RAG_INDEX_READY],
    )
