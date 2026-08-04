#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
AIRFLOW_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
COMPOSE_FILE="$AIRFLOW_DIR/docker-compose.yml"
DUMP_FILE="${1:-}"
TARGET_DB="jobrag_restore_test_$(date -u +%Y%m%d%H%M%S)"

if [[ -z "$DUMP_FILE" ]]; then
    echo "usage: $0 JOBRAG_DUMP" >&2
    exit 2
fi

compose() {
    docker compose --project-directory "$AIRFLOW_DIR" -f "$COMPOSE_FILE" "$@"
}

cleanup() {
    compose exec -T postgres dropdb -U postgres --if-exists --force "$TARGET_DB" >/dev/null 2>&1 || true
}
trap cleanup EXIT

bash "$SCRIPT_DIR/restore-jobrag-to-new-db.sh" "$DUMP_FILE" "$TARGET_DB"

counts="$(compose exec -T postgres psql -U postgres -d "$TARGET_DB" -At \
    -F ',' -v ON_ERROR_STOP=1 -c \
    "SELECT (SELECT count(*) FROM job_postings), (SELECT count(*) FROM postings), (SELECT count(*) FROM chunks), (SELECT count(*) FROM chunks WHERE embedding IS NULL)")"
orphans="$(compose exec -T postgres psql -U postgres -d "$TARGET_DB" -At \
    -v ON_ERROR_STOP=1 -c \
    "SELECT count(*) FROM chunks c LEFT JOIN postings p ON p.uid = c.posting_uid WHERE p.uid IS NULL")"

if [[ "$orphans" != "0" ]]; then
    echo "restore drill failed: orphan chunks=$orphans" >&2
    exit 1
fi

echo "[restore-test] status=completed target=$TARGET_DB counts=$counts orphan_chunks=$orphans"
