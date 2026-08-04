#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
AIRFLOW_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
REPO_DIR="$(cd -- "$AIRFLOW_DIR/../.." && pwd -P)"
COMPOSE_FILE="$AIRFLOW_DIR/docker-compose.yml"

BACKUP_DIR="${BACKUP_DIR:-${1:-}}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
JOBRAG_DB_NAME="${JOBRAG_DB_NAME:-jobrag}"

if [[ -z "$BACKUP_DIR" ]]; then
    echo "usage: BACKUP_DIR=/separate/disk/jobis-backups $0" >&2
    exit 2
fi
if [[ ! "$RETENTION_DAYS" =~ ^[0-9]+$ ]]; then
    echo "RETENTION_DAYS must be a non-negative integer" >&2
    exit 2
fi
if [[ ! "$JOBRAG_DB_NAME" =~ ^[a-z][a-z0-9_]{0,62}$ ]]; then
    echo "invalid JOBRAG_DB_NAME: $JOBRAG_DB_NAME" >&2
    exit 2
fi

mkdir -p -- "$BACKUP_DIR"
BACKUP_DIR="$(cd -- "$BACKUP_DIR" && pwd -P)"
if [[ "$BACKUP_DIR" == "/" ]]; then
    echo "BACKUP_DIR must not be the filesystem root" >&2
    exit 2
fi

compose() {
    docker compose --project-directory "$AIRFLOW_DIR" -f "$COMPOSE_FILE" "$@"
}

checksum() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1"
    else
        shasum -a 256 "$1"
    fi
}

backup_database() {
    local database="$1"
    local destination="$2"
    local temporary="${destination}.tmp"

    rm -f -- "$temporary"
    compose exec -T postgres pg_dump \
        -U postgres -d "$database" --format=custom --no-owner --no-privileges \
        > "$temporary"
    compose exec -T postgres pg_restore --list < "$temporary" >/dev/null
    mv -- "$temporary" "$destination"
    checksum "$destination" > "${destination}.sha256"
}

psql_scalar() {
    local database="$1"
    local sql="$2"
    compose exec -T postgres psql \
        -U postgres -d "$database" -At -v ON_ERROR_STOP=1 -c "$sql" \
        | tr -d '\r'
}

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
jobrag_dump="$BACKUP_DIR/${JOBRAG_DB_NAME}-${timestamp}.dump"
airflow_dump="$BACKUP_DIR/airflow-${timestamp}.dump"
manifest="$BACKUP_DIR/manifest-${timestamp}.txt"

backup_database "$JOBRAG_DB_NAME" "$jobrag_dump"
backup_database airflow "$airflow_dump"

git_revision="$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || printf 'unknown')"
postgres_version="$(psql_scalar postgres "SHOW server_version")"
flyway_version="$(psql_scalar "$JOBRAG_DB_NAME" "SELECT COALESCE((SELECT version FROM flyway_schema_history WHERE success ORDER BY installed_rank DESC LIMIT 1), 'none')" 2>/dev/null || printf 'none')"
job_postings_count="$(psql_scalar "$JOBRAG_DB_NAME" "SELECT count(*) FROM job_postings")"
postings_count="$(psql_scalar "$JOBRAG_DB_NAME" "SELECT count(*) FROM postings")"
chunks_count="$(psql_scalar "$JOBRAG_DB_NAME" "SELECT count(*) FROM chunks")"
dag_runs_count="$(psql_scalar airflow "SELECT count(*) FROM dag_run")"

{
    printf 'created_at_utc=%s\n' "$timestamp"
    printf 'git_revision=%s\n' "$git_revision"
    printf 'postgres_version=%s\n' "$postgres_version"
    printf 'jobrag_database=%s\n' "$JOBRAG_DB_NAME"
    printf 'flyway_version=%s\n' "$flyway_version"
    printf 'job_postings=%s\n' "$job_postings_count"
    printf 'postings=%s\n' "$postings_count"
    printf 'chunks=%s\n' "$chunks_count"
    printf 'airflow_dag_runs=%s\n' "$dag_runs_count"
    printf 'jobrag_dump=%s\n' "$(basename -- "$jobrag_dump")"
    printf 'airflow_dump=%s\n' "$(basename -- "$airflow_dump")"
} > "$manifest"
checksum "$manifest" > "${manifest}.sha256"

find "$BACKUP_DIR" -maxdepth 1 -type f -mtime "+$RETENTION_DAYS" \
    \( -name '*.dump' -o -name '*.dump.sha256' -o -name 'manifest-*.txt' \
       -o -name 'manifest-*.txt.sha256' \) -delete

echo "[backup] status=completed created_at_utc=$timestamp directory=$BACKUP_DIR"
