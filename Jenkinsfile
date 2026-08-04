// JOBIS Jenkins CI/CD
//
//   모든 브랜치 push/MR : CI (backend + AI/v2bridge + frontend + RAG + infra)
//   master push(병합)   : CI 통과 후 운영 서버 자동 배포
//
// 사전 설정은 ops/JENKINS_SETUP.md 참고.
// 필요 플러그인: Docker Pipeline, SSH Agent, JUnit, GitLab
// 필요 Jenkins 설정: DEPLOY_HOST 전역 환경변수, 'jobis-deploy-ssh' SSH 자격증명,
//                    GitLab 연결 'ssafy-gitlab' (Manage Jenkins → System → GitLab)

pipeline {
  agent none

  options {
    disableConcurrentBuilds()
    timeout(time: 45, unit: 'MINUTES')
    gitLabConnection('ssafy-gitlab')   // 빌드 상태를 GitLab 커밋/MR에 보고
  }

  stages {

    stage('Backend: test & package') {
      agent any
      steps {
        updateGitlabCommitStatus name: 'jenkins', state: 'running'
        script {
          // 운영 DB가 PostgreSQL이므로 CI도 동일한 DB로 테스트한다 (방언 불일치 방지)
          docker.image('postgres:17-alpine').withRun(
            '-e POSTGRES_DB=jobiss ' +
            '-e POSTGRES_USER=jobiss_migrator ' +
            '-e POSTGRES_PASSWORD=ci-migrator-password'
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

            docker.image('eclipse-temurin:17-jdk').inside("--link ${db.id}:postgres") {
              withEnv([
                'DB_URL=jdbc:postgresql://postgres:5432/jobiss',
                'DB_MIGRATOR_USER=jobiss_migrator',
                'DB_MIGRATOR_PASSWORD=ci-migrator-password',
                'DB_APP_USER=jobiss_app',
                'DB_APP_PASSWORD=ci-app-password',
                'AI_WORKER_ENABLED=false',
                'JWT_SECRET=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef'
              ]) {
              sh '''
                cd backend
                chmod +x gradlew
                ./gradlew clean test bootJar --no-daemon
                jar="$(find build/libs -maxdepth 1 -type f -name '*.jar' ! -name '*-plain.jar' -print -quit)"
                test -n "$jar" || { echo "실행 가능한 JAR 없음"; exit 1; }
                cp "$jar" backend.jar
              '''
              }
            }
          }
        }
        junit 'backend/build/test-results/test/*.xml'
        stash name: 'backend-jar', includes: 'backend/backend.jar'
      }
    }

    stage('AI v2bridge: test') {
      agent {
        docker { image 'python:3.11-slim' }
      }
      steps {
        sh '''
          export PYTHONUTF8=1
          export UV_CACHE_DIR=/tmp/jobis-uv-cache
          export UV_PROJECT_ENVIRONMENT=/tmp/jobis-ai-venv

          python -m venv /tmp/jobis-uv-bootstrap
          /tmp/jobis-uv-bootstrap/bin/python -m pip install \
            --disable-pip-version-check --no-cache-dir uv==0.11.32

          cd AI
          /tmp/jobis-uv-bootstrap/bin/uv run \
            --frozen --extra dev --extra prototype pytest -q
          /tmp/jobis-uv-bootstrap/bin/uv run \
            --frozen --extra prototype python -m jobis_ai.explain \
            > /tmp/jobis-ai-explain.txt
        '''
      }
    }

    stage('Frontend: typecheck & build') {
      agent {
        docker { image 'node:22-alpine' }
      }
      steps {
        sh '''
          cd frontend
          npm ci --ignore-scripts
          npm run build
        '''
      }
    }

    stage('RAG: static validation') {
      agent {
        docker { image 'python:3.12-slim' }
      }
      steps {
        sh '''
          python -m pip install --disable-pip-version-check --no-cache-dir rank_bm25==0.2.2
          python -m compileall -q RAG
          python -m unittest discover -s RAG/tests -v
        '''
      }
    }

    stage('Infra: static validation') {
      agent any
      steps {
        sh '''
          test -x ops/deploy-jobis-container
          bash -n ops/deploy-jobis-container
          bash -n ops/backup-jobis-db
          bash -n ops/restore-jobis-db-test
          bash -n ops/restore-latest-jobis-db-test
          bash -n ops/test-db-backup-restore
          bash -n ops/test-v2-database-bootstrap
          bash -n ops/prepare-jobis-server
          bash -n ops/audit-jobis-server
          bash -n ops/switch-jobis-nginx
          bash -n ops/install-jobis-nginx-control
          bash -n ops/bootstrap-jobis-v2-database
          bash -n ops/configure-jobis-v2-environment
          bash -n ops/migrate-jobis-legacy-to-v2
          bash -n ops/prepare-jobis-v2-release
          bash -n ops/test-legacy-data-migration
          git diff --check HEAD^ HEAD

          docker run --rm \
            -v "$WORKSPACE:/workspace:ro" \
            -w /workspace \
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
          docker run --rm -i \
            -e JOBIS_SHA=0000000000000000000000000000000000000000 \
            docker:28-cli \
            sh -ec '
              mkdir -p /etc/jobis
              : > /etc/jobis/jobis-v2.env
              exec docker compose --project-name jobis-validation -f - \
                config --quiet --no-path-resolution --no-env-resolution
            ' \
            < ops/docker-compose.prod.yml

          docker run --rm \
            -v "$WORKSPACE:/workspace:ro" \
            -v "$WORKSPACE/ops/nginx-jobis-upstream-container.conf:/etc/jobis/nginx-active-upstream.conf:ro" \
            nginx:1.27-alpine \
            nginx -t -c /workspace/ops/nginx-jobis-app.test.conf

          bash ops/test-db-backup-restore
          bash ops/test-v2-database-bootstrap
          bash ops/test-legacy-data-migration
        '''
      }
    }

    // develop에서도 컨테이너 빌드를 검증한다. JOBIS_IMAGE_PREFIX가 설정된 표준 구성은
    // registry에 불변 SHA 태그를 push해 별도 배포 서버에서도 같은 이미지를 pull한다.
    stage('Docker images: build') {
      when {
        anyOf {
          branch 'develop'
          branch 'master'
        }
      }
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
              '''
            }
          } else {
            echo 'JOBIS_IMAGE_PREFIX is empty; using the same-Docker-daemon deployment mode.'
          }
        }
      }
    }

    stage('Deploy production') {
      when { branch 'master' }
      agent any
      // 위 단계가 만든 세 이미지를 서버 배포 명령이 백업 후 원자적으로 교체한다.
      steps {
        sshagent(credentials: ['jobis-deploy-ssh']) {
          sh '''
            test -n "$DEPLOY_HOST" || { echo "DEPLOY_HOST 전역 환경변수가 없습니다."; exit 1; }
            ssh -o StrictHostKeyChecking=accept-new \
              "jobis-deploy@$DEPLOY_HOST" \
              "sudo -n /usr/local/sbin/audit-jobis-server '$GIT_COMMIT' predeploy && \
               sudo -n /usr/local/sbin/deploy-jobis '$GIT_COMMIT'"
          '''
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
