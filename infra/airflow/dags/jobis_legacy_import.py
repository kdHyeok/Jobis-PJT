"""레거시 SQLite의 본문 완료·OCR 대기 공고를 PostgreSQL로 가져오는 수동 DAG."""
from airflow import DAG
from airflow.operators.bash import BashOperator

from jobis_common import (
    DEFAULT_ARGS,
    JOB_POSTINGS_LOADED,
    POSTINGS_READY_FOR_RAG,
    START_DATE,
)


DATA_DIR = "/opt/jobis/DATA"
LEGACY_SQLITE = "/opt/jobis/imports/all_job_postings.db"
IMPORT_SQL = "exports/legacy_job_postings_import.sql"
VERIFY_SQL = "exports/legacy_job_postings_verify.sql"


with DAG(
    dag_id="jobis_legacy_import",
    description="레거시 SQLite의 본문 완료·OCR 대기 공고를 검증·staging 후 PostgreSQL에 UPSERT",
    schedule=None,
    start_date=START_DATE,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["jobis", "one-time", "import"],
) as dag:
    validate_sqlite = BashOperator(
        task_id="validate_sqlite",
        bash_command=(
            f"cd {DATA_DIR} && python import_legacy_sqlite.py validate "
            f"--sqlite {LEGACY_SQLITE}"
        ),
    )

    prepare_import = BashOperator(
        task_id="prepare_import",
        bash_command=(
            f"cd {DATA_DIR} && python import_legacy_sqlite.py prepare "
            f"--sqlite {LEGACY_SQLITE} --import-sql {IMPORT_SQL} --verify-sql {VERIFY_SQL}"
        ),
    )

    import_postgres = BashOperator(
        task_id="import_postgres",
        bash_command=(
            f"cd {DATA_DIR} && psql \"$JOBRAG_PG_DSN\" -v ON_ERROR_STOP=1 -f {IMPORT_SQL}"
        ),
    )

    verify_import = BashOperator(
        task_id="verify_import",
        bash_command=(
            f"cd {DATA_DIR} && psql \"$JOBRAG_PG_DSN\" -v ON_ERROR_STOP=1 -f {VERIFY_SQL}"
        ),
        outlets=[JOB_POSTINGS_LOADED, POSTINGS_READY_FOR_RAG],
    )

    validate_sqlite >> prepare_import >> import_postgres >> verify_import
