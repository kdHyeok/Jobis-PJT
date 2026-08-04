#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
AIRFLOW_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
COMPOSE_FILE="$AIRFLOW_DIR/docker-compose.yml"

DUMP_FILE="${1:-}"
TARGET_DB="${2:-}"

if [[ -z "$DUMP_FILE" || -z "$TARGET_DB" ]]; then
    echo "usage: $0 JOBRAG_DUMP NEW_DATABASE_NAME" >&2
    exit 2
fi
if [[ ! -f "$DUMP_FILE" ]]; then
    echo "dump file not found: $DUMP_FILE" >&2
    exit 2
fi
if [[ ! "$TARGET_DB" =~ ^[a-z][a-z0-9_]{0,62}$ ]]; then
    echo "invalid target database name: $TARGET_DB" >&2
    exit 2
fi
case "$TARGET_DB" in
    jobrag|airflow|postgres|template0|template1)
        echo "refusing to restore over a protected database: $TARGET_DB" >&2
        exit 2
        ;;
esac

compose() {
    docker compose --project-directory "$AIRFLOW_DIR" -f "$COMPOSE_FILE" "$@"
}

exists="$(compose exec -T postgres psql -U postgres -d postgres -At \
    -c "SELECT 1 FROM pg_database WHERE datname = '$TARGET_DB'")"
if [[ "$exists" == "1" ]]; then
    echo "target database already exists; refusing to overwrite: $TARGET_DB" >&2
    exit 2
fi

created=0
cleanup_failed_restore() {
    local status=$?
    if [[ $status -ne 0 && $created -eq 1 ]]; then
        compose exec -T postgres dropdb -U postgres --if-exists --force "$TARGET_DB" >/dev/null 2>&1 || true
    fi
    exit "$status"
}
trap cleanup_failed_restore EXIT

compose exec -T postgres createdb -U postgres --owner=jobrag "$TARGET_DB"
created=1
compose exec -T postgres psql -U postgres -d "$TARGET_DB" \
    -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS vector" >/dev/null
compose exec -T postgres pg_restore -U postgres \
    --dbname="$TARGET_DB" --no-owner --no-privileges --exit-on-error \
    < "$DUMP_FILE"

# The extension stays owned by postgres, while application relations return to
# the jobrag owner so later Flyway migrations can alter them.
compose exec -T postgres psql -U postgres -d "$TARGET_DB" -v ON_ERROR_STOP=1 <<'SQL'
DO $ownership$
DECLARE
    item RECORD;
BEGIN
    FOR item IN
        SELECT n.nspname, c.relname, c.relkind
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind IN ('r', 'p', 'S')
          AND NOT EXISTS (
              SELECT 1
              FROM pg_depend d
              WHERE d.classid = 'pg_class'::regclass
                AND d.objid = c.oid
                AND d.deptype = 'e'
          )
    LOOP
        IF item.relkind = 'S' THEN
            EXECUTE format('ALTER SEQUENCE %I.%I OWNER TO jobrag', item.nspname, item.relname);
        ELSE
            EXECUTE format('ALTER TABLE %I.%I OWNER TO jobrag', item.nspname, item.relname);
        END IF;
    END LOOP;
END
$ownership$;
SQL

# Old dumps may predate Flyway. Baseline them at 0 and apply every pending migration.
compose run --rm -e "FLYWAY_URL=jdbc:postgresql://postgres:5432/$TARGET_DB" \
    jobrag-migrate

schema_check="$(compose exec -T postgres psql -U postgres -d "$TARGET_DB" -At \
    -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM pg_class WHERE relkind = 'r' AND relname IN ('job_postings', 'postings', 'chunks', 'flyway_schema_history')")"
if [[ "$schema_check" != "4" ]]; then
    echo "restore validation failed: expected four required tables, found $schema_check" >&2
    exit 1
fi

trap - EXIT
echo "[restore] status=completed target_database=$TARGET_DB"
echo "Set JOBRAG_DB_NAME=$TARGET_DB only after the restore drill and application checks pass."
