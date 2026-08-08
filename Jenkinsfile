// JOBIS Jenkins CI/CD
//
//   기능 브랜치/develop : CI (backend + AI/v2bridge + frontend + RAG + infra)
//   develop             : CI 통과 후 여섯 SHA 이미지 build/push
//   master 병합         : develop에서 검증한 동일 트리와 이미지를 승격한 뒤 자동 배포
//
// ── 소유권 경계 ────────────────────────────────────────────────────────────
// 이 파일은 CI/CD 뼈대다. Infra 담당이 소유하고, 기능 개발자는 원칙적으로 고치지 않는다.
//   이 파일이 정하는 것 : 스테이지 구성과 순서, 브랜치 게이트(when), 실행 컨테이너 이미지,
//                        서비스 컨테이너(PostgreSQL 등), 자격증명, 이미지 승격, 배포
//   서비스가 정하는 것  : 무엇을 검사하는가 — backend/ci/test.sh, AI/ci/test.sh,
//                        frontend/ci/test.sh, RAG/ci/test.sh
//
// 기능을 추가·수정할 때 개발자가 고칠 파일은 자기 서비스의 ci/test.sh 와 테스트 코드다.
// 새 인프라 의존성(Redis 등)이나 게이트 정책 변경이 필요하면 이 파일을 바꾸는 MR을 올리고
// Infra 리뷰를 받는다(.gitlab/CODEOWNERS). 자세한 규칙은 루트 AGENTS.md "CI/CD 소유권".
// ──────────────────────────────────────────────────────────────────────────
//
// 사전 설정은 ops/JENKINS_SETUP.md 참고.
// 필요 플러그인: Docker Pipeline, SSH Agent, JUnit, GitLab
// 필요 Jenkins 설정: DEPLOY_HOST 전역 환경변수, 'jobis-deploy-ssh' SSH 자격증명,
//                    GitLab 연결 'ssafy-gitlab' (Manage Jenkins → System → GitLab)

pipeline {
  agent none

  environment {
    // 호스트 postgres(5432)와 겹치지 않는 CI 전용 포트. disableConcurrentBuilds 로
    // 동시 실행이 없으므로 고정 포트를 써도 충돌하지 않는다.
    CI_POSTGRES_PORT = '55432'
  }

  options {
    disableConcurrentBuilds()
    timeout(time: 45, unit: 'MINUTES')
    gitLabConnection('ssafy-gitlab')   // 빌드 상태를 GitLab 커밋/MR에 보고
  }

  stages {

    stage('Master release: verify') {
      when { branch 'master' }
      agent any
      steps {
        updateGitlabCommitStatus name: 'jenkins', state: 'running'
        sh '''
          set -euo pipefail
          set -- $(git rev-list --parents -n 1 "$GIT_COMMIT")
          if [ "$#" -ne 3 ]; then
            echo 'master releases must be two-parent merges from tested develop.' >&2
            exit 1
          fi
          tested_develop_sha="$3"
          if ! git merge-base --is-ancestor "$tested_develop_sha" origin/develop; then
            echo "The release parent is not part of origin/develop: $tested_develop_sha" >&2
            exit 1
          fi
          if ! git diff --quiet "$GIT_COMMIT" "$tested_develop_sha"; then
            echo 'The master merge tree differs from its tested develop parent.' >&2
            echo 'Resolve the difference in develop and run the full CI again.' >&2
            exit 1
          fi
          echo "Promoting tested develop release: $tested_develop_sha"
        '''
      }
    }

    // 직전에 통과한 내용과 같은 서비스는 건너뛴다. 이 서버는 Jenkins와 운영이 같은 호스트를
    // 쓰고(가용 메모리 약 2GB·스왑 0·executor 2) 스테이지 병렬화는 OOM 위험이 있어,
    // 부하를 줄이는 수단으로 병렬 대신 재실행 생략을 쓴다.
    //
    // 안전 규칙 두 가지:
    //   1) fail-open — 표식이 없거나 읽지 못하면 **실행한다.** 판단이 안 서면 건너뛰지 않는다.
    //   2) develop·master 에서는 절대 건너뛰지 않는다. 'Master release: verify' 가 보장하는
    //      "master 트리 == 검증된 develop 트리"는 develop 이 전부 실행됐을 때만 뜻이 있다.
    // 표식은 스테이지가 **성공한 뒤에만** 쓴다(.ci-cache/, 워크스페이스 로컬·git 무시).
    stage('CI plan') {
      when { not { branch 'master' } }
      agent any
      steps {
        script {
          boolean cacheable = env.BRANCH_NAME != 'develop'
          if (!cacheable) {
            echo '[plan] develop 은 통합 게이트다 — 모든 스테이지를 실행한다.'
          }
          [
            BACKEND : 'backend',
            AI      : 'AI',
            FRONTEND: 'frontend',
            RAG     : 'RAG',
            INFRA   : 'ops infra compose.yaml .env.production.example'
          ].each { key, paths ->
            // Jenkinsfile 을 함께 해싱한다 — 뼈대가 바뀌면 전 서비스를 다시 검증한다.
            String name = key.toString()
            String sha = sh(
              script: "git ls-tree -r HEAD -- ${paths} Jenkinsfile | sha1sum | cut -c1-40",
              returnStdout: true
            ).trim()
            env.setProperty("SHA_${name}".toString(), sha)
            boolean unchanged = cacheable && sha && sh(
              script: "test -f .ci-cache/${name}.sha && " +
                      "[ \"\$(cat .ci-cache/${name}.sha)\" = '${sha}' ]",
              returnStatus: true
            ) == 0
            env.setProperty("SKIP_${name}".toString(), unchanged ? 'true' : 'false')
            echo unchanged
              ? "[plan] skip ${key} — 직전 통과 이후 변경 없음 (${sha})"
              : "[plan] run  ${key}"
          }
        }
      }
    }

    stage('Backend: test & package') {
      when {
        beforeAgent true
        allOf {
          not { branch 'master' }
          expression { env.SKIP_BACKEND != 'true' }
        }
      }
      agent any
      post {
        success {
          sh 'mkdir -p .ci-cache && printf %s "$SHA_BACKEND" > .ci-cache/BACKEND.sha'
        }
      }
      steps {
        updateGitlabCommitStatus name: 'jenkins', state: 'running'
        script {
          // 운영 DB가 PostgreSQL이므로 CI도 동일한 DB로 테스트한다 (방언 불일치 방지)
          // 아래 테스트 에이전트는 Testcontainers 를 쓰기 위해 host 네트워크로 실행한다.
          // host 네트워크에서는 --link 를 쓸 수 없으므로 루프백 포트로 발행해 연결한다.
          docker.image('postgres:17-alpine').withRun(
            '-e POSTGRES_DB=jobiss ' +
            '-e POSTGRES_USER=jobiss_migrator ' +
            '-e POSTGRES_PASSWORD=ci-migrator-password ' +
            "-p 127.0.0.1:${CI_POSTGRES_PORT}:5432"
          ) { db ->
            // 현재 서비스 v2는 Flyway용 역할과 RLS가 적용되는 앱 역할을 분리한다.
            withEnv(["POSTGRES_CONTAINER=${db.id}"]) {
              sh '''
                ready=false
                for i in $(seq 1 30); do
                  if docker exec "$POSTGRES_CONTAINER" \
                    pg_isready -h 127.0.0.1 -U jobiss_migrator -d jobiss >/dev/null 2>&1; then
                    ready=true
                    break
                  fi
                  sleep 2
                done
                [ "$ready" = true ] || { echo "PostgreSQL not ready"; exit 1; }

                docker exec -i "$POSTGRES_CONTAINER" \
                  psql -v ON_ERROR_STOP=1 -U jobiss_migrator -d jobiss <<'SQL'
                DO $do$
                BEGIN
                  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jobiss_app') THEN
                    CREATE ROLE jobiss_app
                      LOGIN PASSWORD 'ci-app-password'
                      NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
                  END IF;
                END
                $do$;
                GRANT CONNECT ON DATABASE jobiss TO jobiss_app;
SQL
              '''
            }

            // 소켓 그룹은 호스트 docker 그룹 GID 를 그대로 쓴다(하드코딩하지 않는다).
            def dockerGid = sh(
              script: 'stat -c %g /var/run/docker.sock',
              returnStdout: true
            ).trim()
            docker.image('eclipse-temurin:17-jdk').inside(
              '--network host ' +
              '-v /var/run/docker.sock:/var/run/docker.sock ' +
              "--group-add ${dockerGid}"
            ) {
              withEnv([
                "DB_URL=jdbc:postgresql://127.0.0.1:${CI_POSTGRES_PORT}/jobiss",
                'DB_MIGRATOR_USER=jobiss_migrator',
                'DB_MIGRATOR_PASSWORD=ci-migrator-password',
                'DB_APP_USER=jobiss_app',
                'DB_APP_PASSWORD=ci-app-password',
                'AI_WORKER_ENABLED=false',
                'JWT_SECRET=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef'
              ]) {
              // 무엇을 검사하는가는 backend 개발자 소유다(backend/ci/test.sh).
              // 이 스테이지는 실행 환경(이미지·DB 컨테이너·DB_* 환경변수)만 책임진다.
              sh 'sh backend/ci/test.sh'
              }
            }
          }
        }
        junit 'backend/build/test-results/test/*.xml'
        stash name: 'backend-jar', includes: 'backend/backend.jar'
      }
    }

    stage('AI v2bridge: test') {
      when {
        beforeAgent true
        allOf {
          not { branch 'master' }
          expression { env.SKIP_AI != 'true' }
        }
      }
      agent {
        docker { image 'python:3.11-slim' }
      }
      post {
        success {
          sh 'mkdir -p .ci-cache && printf %s "$SHA_AI" > .ci-cache/AI.sha'
        }
      }
      steps {
        // 검사 내용은 AI 개발자 소유다(AI/ci/test.sh).
        sh 'sh AI/ci/test.sh'
      }
    }

    stage('Frontend: typecheck & build') {
      when {
        beforeAgent true
        allOf {
          not { branch 'master' }
          expression { env.SKIP_FRONTEND != 'true' }
        }
      }
      agent {
        docker { image 'node:22-alpine' }
      }
      post {
        success {
          sh 'mkdir -p .ci-cache && printf %s "$SHA_FRONTEND" > .ci-cache/FRONTEND.sha'
        }
      }
      steps {
        // 검사 내용은 프론트엔드 개발자 소유다(frontend/ci/test.sh).
        sh 'sh frontend/ci/test.sh'
      }
    }

    stage('RAG: static validation') {
      when {
        beforeAgent true
        allOf {
          not { branch 'master' }
          expression { env.SKIP_RAG != 'true' }
        }
      }
      agent {
        docker { image 'python:3.12-slim' }
      }
      post {
        success {
          sh 'mkdir -p .ci-cache && printf %s "$SHA_RAG" > .ci-cache/RAG.sha'
        }
      }
      steps {
        // 검사 내용은 RAG 개발자 소유다(RAG/ci/test.sh).
        sh 'sh RAG/ci/test.sh'
      }
    }

    stage('Infra: static validation') {
      when {
        beforeAgent true
        allOf {
          not { branch 'master' }
          expression { env.SKIP_INFRA != 'true' }
        }
      }
      agent any
      post {
        success {
          sh 'mkdir -p .ci-cache && printf %s "$SHA_INFRA" > .ci-cache/INFRA.sha'
        }
      }
      steps {
        sh '''
          test -x ops/deploy-jobis-container
          # 실행 비트가 빠지면 배포가 시작 직후 "not executable" 로 멈춘다.
          test -x ops/verify-jobis-release
          bash -n ops/deploy-jobis-container
          bash -n ops/backup-jobis-db
          bash -n ops/backup-jobis-pipeline-db
          bash -n ops/restore-jobis-db-test
          bash -n ops/restore-latest-jobis-db-test
          bash -n ops/test-db-backup-restore
          bash -n ops/test-v2-database-bootstrap
          bash -n ops/prepare-jobis-server
          bash -n ops/audit-jobis-server
          bash -n ops/verify-jobis-release
          bash -n ops/switch-jobis-nginx
          bash -n ops/install-jobis-nginx-control
          bash -n ops/bootstrap-jobis-v2-database
          bash -n ops/bootstrap-jobis-pipeline-databases
          bash -n ops/configure-jobis-v2-environment
          bash -n ops/migrate-jobis-legacy-to-v2
          bash -n ops/prepare-jobis-v2-release
          bash -n ops/sync-jobis-release-assets
          bash -n ops/test-legacy-data-migration
          bash -n ops/test-release-migrations
          # 공백 오류는 병합 시점이 아니라 브랜치에서 잡는다.
          #
          # `HEAD^ HEAD` 만 보면 검사 범위가 커밋 위상에 따라 달라진다 — 기능 브랜치에서는
          # 마지막 커밋 하나뿐이고, develop 에서는 HEAD 가 병합 커밋이라 통합분 전체다.
          # 그래서 브랜치 CI 가 초록이어도 병합 순간 처음 보는 오류가 쏟아진다(실측:
          # develop #34 에서 39건). 브랜치가 develop 에 더하는 전체 범위를 본다.
          #
          # develop 에서는 merge-base 가 HEAD 자신이라 비교 대상이 없으므로 HEAD^(병합 전
          # develop)로 되돌린다. origin/develop 을 못 찾을 때도 같은 폴백을 쓴다 —
          # 판단이 안 서면 덜 보지 않는다.
          whitespace_base="$(git merge-base origin/develop HEAD 2>/dev/null || true)"
          if [ -z "$whitespace_base" ] || [ "$whitespace_base" = "$(git rev-parse HEAD)" ]; then
            whitespace_base="$(git rev-parse HEAD^)"
          fi
          echo "[whitespace] ${whitespace_base}..HEAD"
          git diff --check "$whitespace_base" HEAD

          # Multibranch workspaces survive branch changes. Git removes deleted tracked
          # files, but ignored and ordinary untracked artifacts under retired services
          # can remain. Fail closed if source was reintroduced, then clean only the two
          # retired paths in this disposable Jenkins workspace.
          legacy_tracked="$(git ls-files -- ai-server fake-ai)"
          if [ -n "$legacy_tracked" ]; then
            echo 'Retired service paths still contain tracked files:' >&2
            printf '%s\n' "$legacy_tracked" >&2
            exit 1
          fi
          git clean -fdx -- ai-server fake-ai

          # Jenkins is itself a container. Raw bind mounts resolve on the host Docker
          # daemon, where the container-only $WORKSPACE path does not exist. Reuse the
          # Jenkins data volume so sibling validation containers see the same checkout.
          jenkins_container="$(cat /etc/hostname)"
          docker run --rm \
            --volumes-from "${jenkins_container}:ro" \
            -w "$WORKSPACE" \
            python:3.12-slim \
            python ops/verify-release-config.py

          # 활성 배포 경로가 제거된 계약 어댑터/fake-ai를 다시 참조하면 실패한다.
          if grep -En 'jobis-fake-ai:|ai-server:|AGENT_WS_URL|AGENT_HTTP_URL' \
            compose.yaml ops/docker-compose.prod.yml; then
            echo 'Legacy AI deployment reference detected.' >&2
            exit 1
          fi

          # Jenkins 컨테이너에는 운영 서버의 /etc/jobis/jobis-v2.env가 없으므로
          # 절대 경로와 env_file 내용은 해석하지 않고 Compose 모델만 검증한다.
          # Jenkins 컨테이너의 Docker CLI에는 Compose 플러그인이 없을 수 있다.
          # Compose가 포함된 공식 CLI 이미지에 파일을 표준입력으로 전달해 모델만 검증한다.
          docker run --rm \
            --volumes-from "${jenkins_container}:ro" \
            -w "$WORKSPACE" \
            -e JOBIS_SHA=0000000000000000000000000000000000000000 \
            docker:28-cli \
            sh -ec '
              mkdir -p /etc/jobis
              : > /etc/jobis/jobis-v2.env
              exec docker compose --project-name jobis-validation \
                --env-file .env.production.example -f ops/docker-compose.prod.yml \
                config --quiet --no-path-resolution --no-env-resolution
            '

          docker run --rm \
            --volumes-from "${jenkins_container}:ro" \
            -e JOBIS_WORKSPACE="$WORKSPACE" \
            nginx:1.27-alpine \
            sh -ec '
              ln -s "$JOBIS_WORKSPACE" /workspace
              mkdir -p /etc/jobis
              cp /workspace/ops/nginx-jobis-upstream-container.conf \
                /etc/jobis/nginx-active-upstream.conf
              exec nginx -t -c /workspace/ops/nginx-jobis-app.test.conf
            '

          bash ops/test-db-backup-restore
          bash ops/test-v2-database-bootstrap
          bash ops/test-legacy-data-migration
        '''
      }
    }

    // develop에서 컨테이너 빌드를 검증한다. JOBIS_IMAGE_PREFIX가 설정된 표준 구성은
    // registry에 불변 SHA 태그를 push해 별도 배포 서버에서도 같은 이미지를 pull한다.
    stage('Docker images: build') {
      when { branch 'develop' }
      agent any
      steps {
        script {
          sh '''
            prefix="${JOBIS_IMAGE_PREFIX:-}"
            case "$prefix" in
              ""|*/) ;;
              *) echo 'JOBIS_IMAGE_PREFIX must be empty or end with /.' >&2; exit 2 ;;
            esac
            case "$prefix" in
              *://*) echo 'JOBIS_IMAGE_PREFIX must not include a URL scheme.' >&2; exit 2 ;;
            esac
            docker build -t "${prefix}jobis-backend:$GIT_COMMIT" backend
            docker build -t "${prefix}jobis-ai:$GIT_COMMIT" AI
            docker build -t "${prefix}jobis-frontend:$GIT_COMMIT" frontend
            docker build -t "${prefix}jobis-rag-search:$GIT_COMMIT" \
              -f infra/airflow/Dockerfile.rag-search .
            docker build -t "${prefix}jobis-rag-ingest:$GIT_COMMIT" \
              -f infra/airflow/Dockerfile.rag-ingest .
            docker build -t "${prefix}jobis-airflow:$GIT_COMMIT" \
              -f infra/airflow/Dockerfile.airflow .
          '''

          if (env.JOBIS_IMAGE_PREFIX?.trim()) {
            withCredentials([usernamePassword(
              credentialsId: 'jobis-container-registry',
              usernameVariable: 'REGISTRY_USER',
              passwordVariable: 'REGISTRY_PASSWORD'
            )]) {
              sh '''
                registry="${JOBIS_IMAGE_PREFIX%%/*}"
                printf '%s' "$REGISTRY_PASSWORD" | docker login "$registry" \
                  --username "$REGISTRY_USER" --password-stdin
                trap 'docker logout "$registry" >/dev/null 2>&1 || true' EXIT
                docker push "${JOBIS_IMAGE_PREFIX}jobis-backend:$GIT_COMMIT"
                docker push "${JOBIS_IMAGE_PREFIX}jobis-ai:$GIT_COMMIT"
                docker push "${JOBIS_IMAGE_PREFIX}jobis-frontend:$GIT_COMMIT"
                docker push "${JOBIS_IMAGE_PREFIX}jobis-rag-search:$GIT_COMMIT"
                docker push "${JOBIS_IMAGE_PREFIX}jobis-rag-ingest:$GIT_COMMIT"
                docker push "${JOBIS_IMAGE_PREFIX}jobis-airflow:$GIT_COMMIT"
              '''
            }
          } else {
            echo 'JOBIS_IMAGE_PREFIX is empty; using the same-Docker-daemon deployment mode.'
          }
        }
      }
    }

    stage('Docker images: promote') {
      when { branch 'master' }
      agent any
      steps {
        script {
          if (env.JOBIS_IMAGE_PREFIX?.trim()) {
            withCredentials([usernamePassword(
              credentialsId: 'jobis-container-registry',
              usernameVariable: 'REGISTRY_USER',
              passwordVariable: 'REGISTRY_PASSWORD'
            )]) {
              sh '''
                set -euo pipefail
                tested_develop_sha="$(git rev-parse "$GIT_COMMIT^2")"
                registry="${JOBIS_IMAGE_PREFIX%%/*}"
                printf '%s' "$REGISTRY_PASSWORD" | docker login "$registry" \
                  --username "$REGISTRY_USER" --password-stdin
                trap 'docker logout "$registry" >/dev/null 2>&1 || true' EXIT
                for image in jobis-backend jobis-ai jobis-frontend \
                             jobis-rag-search jobis-rag-ingest jobis-airflow; do
                  source="${JOBIS_IMAGE_PREFIX}${image}:${tested_develop_sha}"
                  target="${JOBIS_IMAGE_PREFIX}${image}:${GIT_COMMIT}"
                  docker pull "$source"
                  docker tag "$source" "$target"
                  docker push "$target"
                done
              '''
            }
          } else {
            sh '''
              set -euo pipefail
              tested_develop_sha="$(git rev-parse "$GIT_COMMIT^2")"
              for image in jobis-backend jobis-ai jobis-frontend \
                           jobis-rag-search jobis-rag-ingest jobis-airflow; do
                source="${image}:${tested_develop_sha}"
                target="${image}:${GIT_COMMIT}"
                if ! docker image inspect "$source" >/dev/null 2>&1; then
                  echo "Tested develop image is missing: $source" >&2
                  echo 'Re-run the develop pipeline before merging to master.' >&2
                  exit 1
                fi
                docker tag "$source" "$target"
              done
            '''
          }
        }
      }
    }

    // CI 는 항상 빈 PostgreSQL 에서 마이그레이션을 검증하므로 "이미 적용된 버전과 어긋난다"는
    // 결함이 구조적으로 걸리지 않는다. 실측(master #9, 2026-08-08): 통합 브랜치가 운영에 이미
    // 적용된 V20~V28 을 삭제·재번호했는데 develop CI 는 끝까지 초록이었고, 배포 시점에 backend
    // 가 기동하지 못해 롤백됐다. 배포 직전에 운영 스냅샷으로 같은 실패를 미리 재현한다.
    //
    // Jenkins 와 배포 호스트가 같은 서버라 호스트의 백업 디렉터리를 그대로 쓴다. 운영 DB 는
    // 읽지도 쓰지도 않고, 덤프를 일회용 컨테이너에 복원해서만 검사한다.
    // JOBIS_BACKUP_DIR 는 Jenkins 전역 환경변수로 설정한다(DEPLOY_HOST 와 같은 방식).
    stage('Release migration gate') {
      when { branch 'master' }
      agent any
      steps {
        sh '''
          set -euo pipefail
          test -n "${JOBIS_BACKUP_DIR:-}" || {
            echo "JOBIS_BACKUP_DIR 전역 환경변수가 없습니다." >&2
            exit 1
          }
          bash ops/test-release-migrations backend/src/main/resources/db/migration
        '''
      }
    }

    stage('Deploy production') {
      when { branch 'master' }
      agent any
      // develop에서 검증하고 위 단계가 승격한 여섯 이미지를 백업 후 원자적으로 교체한다.
      steps {
        sshagent(credentials: ['jobis-deploy-ssh']) {
          withCredentials([file(
            credentialsId: 'jobis-deploy-known-hosts',
            variable: 'DEPLOY_KNOWN_HOSTS'
          )]) {
            sh '''
              set -euo pipefail
              test -n "$DEPLOY_HOST" || { echo "DEPLOY_HOST 전역 환경변수가 없습니다."; exit 1; }
              local_archive="/tmp/jobis-release-${GIT_COMMIT}.tar.gz"
              remote_archive="/home/jobis-deploy/jobis-release-${GIT_COMMIT}.tar.gz"
              trap 'rm -f "$local_archive"' EXIT
              tar -czf "$local_archive" \
                .env.production.example ops infra/airflow/migrations/jobrag
              scp -o UserKnownHostsFile="$DEPLOY_KNOWN_HOSTS" \
                -o StrictHostKeyChecking=yes \
                "$local_archive" "jobis-deploy@$DEPLOY_HOST:$remote_archive"
              ssh -o UserKnownHostsFile="$DEPLOY_KNOWN_HOSTS" \
                -o StrictHostKeyChecking=yes \
                "jobis-deploy@$DEPLOY_HOST" \
                "chmod 600 '$remote_archive' && \
                 sudo -n /usr/local/sbin/sync-jobis-release-assets '$remote_archive' '$GIT_COMMIT' && \
                 sudo -n /usr/local/sbin/audit-jobis-server '$GIT_COMMIT' predeploy && \
                 sudo -n /usr/local/sbin/deploy-jobis '$GIT_COMMIT'"
            '''
          }
        }
      }
    }

    // 배포 스크립트 안에서도 같은 검증을 돌려 실패 시 롤백하지만, 롤백까지 끝난 뒤의
    // 최종 상태를 파이프라인에서 다시 확인한다. 컨테이너가 떠 있는지가 아니라
    // 실제로 동작하는지를 본다: 앱 헬스, 프론트→백엔드 프록시, 임베딩 질의,
    // Airflow 메타DB·스케줄러·DAG import, 워커 큐 정체, nginx 외부 경로.
    stage('Verify production') {
      when { branch 'master' }
      agent any
      steps {
        sshagent(credentials: ['jobis-deploy-ssh']) {
          withCredentials([file(
            credentialsId: 'jobis-deploy-known-hosts',
            variable: 'DEPLOY_KNOWN_HOSTS'
          )]) {
            sh '''
              set -euo pipefail
              test -n "$DEPLOY_HOST" || { echo "DEPLOY_HOST 전역 환경변수가 없습니다."; exit 1; }
              ssh -o UserKnownHostsFile="$DEPLOY_KNOWN_HOSTS" \
                -o StrictHostKeyChecking=yes \
                "jobis-deploy@$DEPLOY_HOST" \
                "sudo -n /usr/local/sbin/verify-jobis-release '$GIT_COMMIT'"
            '''
          }
        }
      }
    }
  }

  post {
    success  { updateGitlabCommitStatus name: 'jenkins', state: 'success' }
    failure  { updateGitlabCommitStatus name: 'jenkins', state: 'failed' }
    aborted  { updateGitlabCommitStatus name: 'jenkins', state: 'canceled' }
  }
}
