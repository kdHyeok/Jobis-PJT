"""정본 Docker/CI/CD 파일 사이의 배포 불변식을 외부 의존성 없이 검사한다."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"release config invalid: {message}")


def main() -> None:
    for removed in ("ai-server", "fake-ai", "docker-compose.yml", "ops/deploy-jobis"):
        candidate = ROOT / removed
        remains = any(path.is_file() for path in candidate.rglob("*")) if candidate.is_dir() else candidate.exists()
        require(not remains, f"legacy path still contains tracked content: {removed}")

    for required in (
        "AI/Dockerfile",
        "backend/Dockerfile",
        "frontend/Dockerfile",
        "compose.yaml",
        "ops/docker-compose.prod.yml",
        "ops/deploy-jobis-container",
        "ops/backup-jobis-db",
        "ops/backup-jobis-pipeline-db",
        "ops/restore-jobis-db-test",
        "ops/restore-latest-jobis-db-test",
        "ops/test-db-backup-restore",
        "ops/test-v2-database-bootstrap",
        "ops/prepare-jobis-server",
        "ops/audit-jobis-server",
        "ops/switch-jobis-nginx",
        "ops/install-jobis-nginx-control",
        "ops/bootstrap-jobis-v2-database",
        "ops/bootstrap-jobis-pipeline-databases",
        "ops/configure-jobis-v2-environment",
        "ops/migrate-jobis-legacy-to-v2",
        "ops/migrate-jobis-legacy-to-v2.sql",
        "ops/prepare-jobis-v2-release",
        "ops/sync-jobis-release-assets",
        "ops/test-legacy-data-migration",
        "ops/jobis-deploy.sudoers",
        "ops/nginx-jobis-app.location.conf",
        "ops/nginx-jobis-upstream-legacy.conf",
        "ops/nginx-jobis-upstream-container.conf",
        "ops/nginx-jobis-app.test.conf",
        "ops/jobis-db-backup.service",
        "ops/jobis-db-backup.timer",
        "ops/jobis-db-restore-drill.service",
        "ops/jobis-db-restore-drill.timer",
        "ops/DEPLOYMENT.md",
        "ops/SERVER_BASELINE.md",
        "backend/src/main/resources/db/migration/V27__legacy_import_audit.sql",
        ".gitlab/merge_request_templates/Release.md",
    ):
        require((ROOT / required).is_file(), f"required file missing: {required}")

    local_compose = text("compose.yaml")
    require("context: ./AI" in local_compose, "local Compose does not build AI/")
    require("AI_SERVER_URL: http://ai:8000" in local_compose, "backend does not target ai service")
    require("jobiss_ai_state:/var/lib/jobis-ai" in local_compose, "AI state volume is missing")
    require("pg_isready -h 127.0.0.1" in local_compose,
            "PostgreSQL health may accept the temporary initialization socket")

    production = text("ops/docker-compose.prod.yml")
    for service in ("ai", "backend", "frontend"):
        require(re.search(rf"(?m)^  {service}:$", production) is not None,
                f"production service missing: {service}")
        require(f"image: ${{JOBIS_IMAGE_PREFIX:-}}jobis-{service}:" in production,
                f"SHA image missing for service: {service}")
    require("service']=='jobis-ai-v2bridge'" in production,
            "AI health does not verify the v2bridge identity")
    require("http://127.0.0.1:8080/api/health" in production,
            "backend DB health endpoint is not configured")
    for service in ("jobrag-migrate", "rag-search", "airflow-init",
                    "airflow-scheduler", "airflow-webserver"):
        require(re.search(rf"(?m)^  {service}:$", production) is not None,
                f"production pipeline service missing: {service}")
    for image in ("jobis-rag-search", "jobis-airflow"):
        require(f"{image}:${{JOBIS_SHA:" in production,
                f"production SHA image missing: {image}")
    require("jobis-rag-ingest:${JOBIS_SHA:" in production,
            "Airflow does not launch the release SHA rag-ingest image")
    require("V3__track_rag_embedding_profile.sql" not in production and
            "/opt/jobis/jobrag-migrations:/flyway/sql:ro" in production,
            "jobrag Flyway migrations are not mounted into production")
    require(production.count("/etc/jobis/jobis-v2.env") >= 5,
            "production services do not share the isolated v2 environment")

    production_env = text(".env.production.example")
    for variable in (
        "DB_URL=",
        "DB_MIGRATOR_USER=",
        "DB_MIGRATOR_PASSWORD=",
        "DB_APP_USER=",
        "DB_APP_PASSWORD=",
        "JOBIS_IMAGE_PREFIX=",
        "JOBIS_BACKUP_DOCKER_NETWORK=host",
        "JOBIS_PIPELINE_BACKUP_DIR=",
        "JOBIS_BACKUP_REQUIRE_SEPARATE_FILESYSTEM=true",
        "JOBIS_REQUIRE_LEGACY_IMPORT=true",
        "AIRFLOW_DB_DSN=",
        "AIRFLOW_FERNET_KEY=",
        "JOBRAG_PG_DSN=",
        "JOBRAG_FLYWAY_URL=",
        "RAG_EMBED_PROVIDER=local",
        "RAG_RERANK_PROVIDER=local",
    ):
        require(variable in production_env,
                f"production environment contract is missing: {variable}")

    pipeline = text("Jenkinsfile")
    stages = re.findall(r"stage\('([^']+)'\)", pipeline)
    expected = [
        "Backend: test & package",
        "AI v2bridge: test",
        "Frontend: typecheck & build",
        "RAG: static validation",
        "Infra: static validation",
        "Docker images: build",
        "Deploy production",
    ]
    require(stages == expected, f"unexpected Jenkins stage order: {stages}")
    for image in ("jobis-ai", "jobis-backend", "jobis-frontend",
                  "jobis-rag-search", "jobis-rag-ingest", "jobis-airflow"):
        require(f'docker build -t "${{prefix}}{image}:$GIT_COMMIT"' in pipeline,
                f"Jenkins does not build {image}")
        require(f'docker push "${{JOBIS_IMAGE_PREFIX}}{image}:$GIT_COMMIT"' in pipeline,
                f"Jenkins does not publish {image}")
    require("branch 'develop'" in pipeline and "branch 'master'" in pipeline,
            "develop/master image gates are missing")
    require("when { branch 'master' }" in pipeline,
            "production deploy is not master-only")
    require("python -m venv /tmp/jobis-rag-venv" in pipeline and
            "rank_bm25==0.2.2" in pipeline and
            "psycopg[binary]==3.2.9" in pipeline and
            "numpy==2.2.6" in pipeline and
            "/tmp/jobis-rag-venv/bin/python -m unittest discover -s RAG/tests -v" in pipeline,
            "RAG CI dependency or strict test gate is missing")
    require("docker { image 'node:22-alpine' }" in pipeline,
            "frontend CI Node image does not match the Docker build")
    require('jenkins_container="$(cat /etc/hostname)"' in pipeline and
            pipeline.count('--volumes-from "${jenkins_container}:ro"') >= 2,
            "sibling validation containers do not share the Jenkins workspace volume")
    require('-v "$WORKSPACE:/workspace:ro"' not in pipeline,
            "Jenkins container workspace is incorrectly used as a host bind mount")
    require("bash ops/test-db-backup-restore" in pipeline,
            "DB backup/restore CI smoke test is missing")
    require("bash -n ops/backup-jobis-pipeline-db" in pipeline,
            "pipeline DB backup syntax gate is missing")
    require("bash ops/test-v2-database-bootstrap" in pipeline,
            "isolated v2 database bootstrap CI smoke test is missing")
    require("bash ops/test-legacy-data-migration" in pipeline,
            "legacy-to-v2 data migration CI smoke test is missing")
    require("pg_isready -h 127.0.0.1 -U jobiss_migrator" in pipeline,
            "Jenkins PostgreSQL readiness may accept the temporary initialization socket")
    for script in (
        "restore-latest-jobis-db-test",
        "prepare-jobis-server",
        "audit-jobis-server",
        "switch-jobis-nginx",
        "install-jobis-nginx-control",
        "bootstrap-jobis-v2-database",
        "bootstrap-jobis-pipeline-databases",
        "configure-jobis-v2-environment",
        "migrate-jobis-legacy-to-v2",
        "prepare-jobis-v2-release",
        "sync-jobis-release-assets",
    ):
        require(f"bash -n ops/{script}" in pipeline,
                f"server script syntax gate is missing: {script}")
    require("nginx -t -c /workspace/ops/nginx-jobis-app.test.conf" in pipeline,
            "Nginx release configuration gate is missing")

    deploy = text("ops/deploy-jobis-container")
    backup_call = deploy.find('"$BACKUP_COMMAND" "$RELEASE_SHA"')
    pipeline_backup_call = deploy.find('"$PIPELINE_BACKUP_COMMAND"', backup_call + 1)
    release_call = deploy.find('compose_up "$RELEASE_SHA"', pipeline_backup_call + 1)
    require(backup_call >= 0 and pipeline_backup_call > backup_call and
            release_call > pipeline_backup_call,
            "deployment does not back up app and pipeline DBs before transition")
    require('compose "$RELEASE_SHA" pull --quiet' in deploy,
            "deployment does not pull registry images")
    require('compose "$PREVIOUS_SHA" pull --quiet' in deploy,
            "rollback does not recover previous registry images")
    require('--project-name "$COMPOSE_PROJECT"' in deploy and
            'readonly COMPOSE_PROJECT="jobis-v2"' in deploy,
            "v2 deployment does not isolate the legacy Compose project")
    require("docker rename jobis-backend" in deploy and
            "docker stop jobis-fake-ai" in deploy,
            "initial legacy containers are not preserved by stop and rename")
    require('"$NGINX_SWITCH_COMMAND" container' in deploy and
            '"$NGINX_SWITCH_COMMAND" legacy' in deploy,
            "deployment and rollback do not switch the Nginx upstream")
    require('"$AUDIT_COMMAND" "$RELEASE_SHA" postdeploy' in deploy,
            "deployment does not run the post-deploy server audit")
    require("docker image rm" not in deploy and "--remove-orphans" not in deploy,
            "deployment may delete preserved legacy images or containers")
    require("trap rollback ERR HUP INT TERM" in deploy,
            "deployment does not roll back on remote-session termination signals")

    backup = text("ops/backup-jobis-db")
    require("JOBIS_BACKUP_REQUIRE_SEPARATE_FILESYSTEM" in backup and
            "Backup storage must use a different filesystem" in backup,
            "backup script does not enforce separate production storage")

    restore = text("ops/restore-jobis-db-test")
    require('JOBIS_RESTORE_PROFILE:-v2' in restore and
            'to_regclass(\'public.users\')' in restore and
            'to_regclass(\'public.flyway_schema_history\')' in restore,
            "restore drill does not distinguish legacy and v2 schemas")

    prepare = text("ops/prepare-jobis-server")
    for installed in (
        "/usr/local/sbin/deploy-jobis",
        "/usr/local/sbin/audit-jobis-server",
        "/usr/local/sbin/backup-jobis-pipeline-db",
        "/usr/local/sbin/switch-jobis-nginx",
        "/usr/local/sbin/install-jobis-nginx-control",
        "/usr/local/sbin/bootstrap-jobis-v2-database",
        "/usr/local/sbin/bootstrap-jobis-pipeline-databases",
        "/usr/local/sbin/configure-jobis-v2-environment",
        "/usr/local/sbin/migrate-jobis-legacy-to-v2",
        "/usr/local/sbin/prepare-jobis-v2-release",
        "/usr/local/sbin/sync-jobis-release-assets",
        "/etc/sudoers.d/jobis-deploy",
        "jobis-db-backup.timer",
        "jobis-db-restore-drill.timer",
    ):
        require(installed in prepare, f"server prepare contract missing: {installed}")
    require("Live Nginx and timers were not enabled automatically" in prepare,
            "server prepare script may mutate unreviewed live routing")

    require("audit-jobis-server '$GIT_COMMIT' predeploy" in pipeline,
            "master deployment does not run the pre-deploy server audit")
    require("StrictHostKeyChecking=yes" in pipeline and
            "jobis-deploy-known-hosts" in pipeline and
            "StrictHostKeyChecking=accept-new" not in pipeline,
            "deployment SSH host key is not pinned")
    require("sync-jobis-release-assets '$remote_archive' '$GIT_COMMIT'" in pipeline,
            "master deployment does not synchronize release assets")

    audit = text("ops/audit-jobis-server")
    for gate in (
        "PostgreSQL connectivity",
        "backup uses a separate filesystem",
        "Nginx routes the application",
        "registry image available",
        "systemd timer enabled",
        "deployed release asset checksums",
        "AI-to-RAG route",
    ):
        require(gate in audit, f"server audit gate missing: {gate}")

    unit_expectations = {
        "ops/jobis-db-backup.service": "/usr/local/sbin/backup-jobis-db manual",
        "ops/jobis-db-backup.timer": "OnCalendar=*-*-* 02:15:00",
        "ops/jobis-db-restore-drill.service": "/usr/local/sbin/restore-latest-jobis-db-test",
        "ops/jobis-db-restore-drill.timer": "OnCalendar=*-*-01 04:15:00",
    }
    for unit, expected_text in unit_expectations.items():
        require(expected_text in text(unit), f"systemd unit contract missing: {unit}")
    for endpoint in (
        "http://127.0.0.1:8000/health",
        "http://127.0.0.1:8080/api/health",
        "http://127.0.0.1:8088/api/auth/csrf",
        "http://127.0.0.1:8765/health",
        "http://127.0.0.1:8081/health",
    ):
        require(endpoint in deploy, f"deploy smoke endpoint missing: {endpoint}")
    require("python -m jobis_ai.readiness --live" in deploy,
            "deploy does not prove live LLM and RAG requests")

    active = "\n".join((local_compose, production))
    for legacy in ("jobis-fake-ai:", "ai-server:", "AGENT_WS_URL", "AGENT_HTTP_URL"):
        require(legacy not in active, f"legacy deployment contract remains: {legacy}")

    print("release-config: ok")


if __name__ == "__main__":
    main()
