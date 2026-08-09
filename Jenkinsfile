// JOBIS Jenkins CI/CD — **파이프라인 뼈대**
//
// 이 파일은 "언제 무엇을 어떤 순서로 돌릴지"와 "무엇이 머지를 막을지"만 정한다.
// "무엇을 검사할지"는 각 영역이 정한다:
//     backend/ci-checks · frontend/ci-checks · AI/ci-checks · RAG/ci-checks
// 영역에 검사를 추가할 때 이 파일을 고치지 않는다. 소유권 규칙은 ops/CI_OWNERSHIP.md.
//
//   기능 브랜치 : 바뀐 영역만 (Detect changes 가 판단) + 정적분석
//   develop     : 전 영역 + 임시 이미지 build → compose 스모크 → 여섯 SHA 이미지 publish
//   master 병합 : develop에서 검증한 동일 트리와 이미지를 승격한 뒤 자동 배포
//
// 한 단계가 실패해도 나머지는 계속 돈다(catchError). 한 번의 파이프라인으로 모든
// 실패를 보기 위해서다. 배포 단계는 앞이 성공했을 때만 진입한다.
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

    // 어떤 영역을 돌릴지 정한다. 기준은 두 가지다.
    //   1) 그 영역이 마지막으로 **통과한 커밋** 이후에 바뀌었는가 (기억이 있으면)
    //   2) 기억이 없으면 origin/develop 과 비교
    // 통과 기록은 빌드 설명(description)에 "ci-pass: backend=<sha> ..." 로 남긴다.
    // Jenkins 재시작·워크스페이스 교체에도 살아남고, 별도 저장소가 필요 없다.
    stage('Detect changes') {
      when { not { branch 'master' } }
      agent any
      steps {
        script {
          // 최근 빌드들을 거슬러 올라가며 통과 기록을 찾는다(마지막 빌드가 실패했어도
          // 그 이전 기록은 유효하다).
          def memo = ''
          def probe = currentBuild.previousBuild
          def hops = 0
          while (probe != null && hops < 15) {
            def desc = probe.description
            if (desc != null && desc.contains('ci-pass:')) {
              memo = desc
              break
            }
            probe = probe.previousBuild
            hops++
          }
          env.CI_PASS_MEMO = memo
          echo('이전 통과 기록: ' + (memo ? memo : '(없음)'))

          // 판단은 셸에서 끝낸다. Jenkins 의 CPS 변환은 클로저(.each/.any)에서 잘 깨지고,
          // 실패하면 이 단계 하나 때문에 파이프라인 전체가 선다.
          def flags = sh(
            script: '''
              set +e
              if [ "$BRANCH_NAME" = "develop" ]; then
                # develop 은 통합 게이트다. 기억과 무관하게 전부 돌린다 — master 는
                # "develop 트리가 통째로 검증됐다"를 전제로 테스트를 생략하기 때문이다.
                echo "backend ai frontend rag infra"
                exit 0
              fi
              if ! git fetch --no-tags --quiet origin develop:refs/remotes/origin/develop; then
                echo 'origin/develop 갱신에 실패해 모든 영역을 실행합니다.' >&2
                echo "backend ai frontend rag infra"
                exit 0
              fi

              # 영역별 기준 커밋: 통과 기록이 있고 그 커밋이 실제로 있으면 그것,
              # 없으면 origin/develop.
              base_for() {
                # 백슬래시 없이 뽑는다 — Groovy 삼중따옴표 문자열은 잘못된 이스케이프를 거부한다.
                sha="$(printf '%s' "$CI_PASS_MEMO" | awk -v key="$1=" '{ for (i = 1; i <= NF; i++) if (index($i, key) == 1) { sub(key, "", $i); print $i } }')"
                if [ -n "$sha" ] && git cat-file -e "$sha^{commit}" 2>/dev/null; then
                  echo "$sha"
                else
                  echo "origin/develop"
                fi
              }

              changed_since() {
                base="$1"; shift
                if [ "$base" = "origin/develop" ]; then
                  if ! diff="$(git diff --name-only origin/develop...HEAD)"; then
                    echo "변경 범위를 계산하지 못해 $base 이후 변경으로 처리합니다." >&2
                    return 0
                  fi
                else
                  if ! diff="$(git diff --name-only "$base" HEAD)"; then
                    echo "변경 범위를 계산하지 못해 $base 이후 변경으로 처리합니다." >&2
                    return 0
                  fi
                fi
                [ -z "$diff" ] && return 1
                # 루트 파일이나 뼈대가 바뀌면 영향 범위를 알 수 없다 — 무조건 돌린다.
                echo "$diff" | grep -qv '/' && return 0
                echo "$diff" | grep -qE "$1"
              }

              out=""
              changed_since "$(base_for backend)"  '^backend/'      && out="$out backend"
              changed_since "$(base_for ai)"       '^AI/'           && out="$out ai"
              changed_since "$(base_for frontend)" '^frontend/'     && out="$out frontend"
              changed_since "$(base_for rag)"      '^(RAG|DATA)/'   && out="$out rag"
              changed_since "$(base_for infra)"    '^(ops|infra)/'  && out="$out infra"
              echo "$out"
              exit 0
            ''',
            returnStdout: true
          ).trim()

          env.RUN_BACKEND = flags.contains('backend') ? 'true' : 'false'
          env.RUN_AI = flags.contains('ai') ? 'true' : 'false'
          env.RUN_FRONTEND = flags.contains('frontend') ? 'true' : 'false'
          env.RUN_RAG = flags.contains('rag') ? 'true' : 'false'
          env.RUN_INFRA = flags.contains('infra') ? 'true' : 'false'
          echo('실행 영역: [' + (flags ? flags : '없음 — 이전 통과 이후 변경 없음') + ']')
        }
      }
    }

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

    stage('Backend: test & package') {
      when {
        allOf {
          not { branch 'master' }
          environment name: 'RUN_BACKEND', value: 'true'
        }
      }
      agent any
      steps {
        // 여기서 실패해도 뒤 단계는 계속 돈다. 한 번의 파이프라인으로 모든
        // 실패를 보기 위해서다. 빌드 결과는 그대로 FAILURE 로 남는다.
        catchError(buildResult: 'FAILURE', stageResult: 'FAILURE') {
          updateGitlabCommitStatus name: 'jenkins', state: 'running'
          script {
            // 운영 DB가 PostgreSQL이므로 CI도 동일한 DB로 테스트한다 (방언 불일치 방지)
            // 아래 테스트 에이전트는 Testcontainers 를 쓰기 위해 host 네트워크로 실행한다.
            // 브랜치별 작업이 겹쳐도 충돌하지 않도록 Docker가 빈 루프백 포트를 고른다.
            docker.image('postgres:17-alpine').withRun(
              '-e POSTGRES_DB=jobiss ' +
              '-e POSTGRES_USER=jobiss_migrator ' +
              '-e POSTGRES_PASSWORD=ci-migrator-password ' +
              '-p 127.0.0.1::5432'
            ) { db ->
              def postgresPort = sh(
                script: "docker port ${db.id} 5432/tcp | sed -n '1s/.*://p'",
                returnStdout: true
              ).trim()
              if (!(postgresPort ==~ /[0-9]+/)) {
                error("PostgreSQL published port is invalid: ${postgresPort}")
              }
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
                  "DB_URL=jdbc:postgresql://127.0.0.1:${postgresPort}/jobiss",
                  'DB_MIGRATOR_USER=jobiss_migrator',
                  'DB_MIGRATOR_PASSWORD=ci-migrator-password',
                  'DB_APP_USER=jobiss_app',
                  'DB_APP_PASSWORD=ci-app-password',
                  'AI_WORKER_ENABLED=false',
                  'JWT_SECRET=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef'
                ]) {
                sh 'chmod +x backend/ci-checks && ./backend/ci-checks test'
                script { env.PASSED_BACKEND = env.GIT_COMMIT }
                }
              }
            }
          }
          junit 'backend/build/test-results/test/*.xml'
          stash name: 'backend-jar', includes: 'backend/backend.jar'
        }
      }
    }

    stage('AI v2bridge: test') {
      when {
        allOf {
          not { branch 'master' }
          environment name: 'RUN_AI', value: 'true'
        }
      }
      agent {
        docker { image 'python:3.11-slim' }
      }
      steps {
        // 여기서 실패해도 뒤 단계는 계속 돈다. 한 번의 파이프라인으로 모든
        // 실패를 보기 위해서다. 빌드 결과는 그대로 FAILURE 로 남는다.
        catchError(buildResult: 'FAILURE', stageResult: 'FAILURE') {
          sh 'chmod +x AI/ci-checks && ./AI/ci-checks test'
          script { env.TESTED_AI = env.GIT_COMMIT }
        }
      }
    }

    stage('Frontend: typecheck & build') {
      when {
        allOf {
          not { branch 'master' }
          environment name: 'RUN_FRONTEND', value: 'true'
        }
      }
      agent {
        docker { image 'node:22-alpine' }
      }
      steps {
        // 여기서 실패해도 뒤 단계는 계속 돈다. 한 번의 파이프라인으로 모든
        // 실패를 보기 위해서다. 빌드 결과는 그대로 FAILURE 로 남는다.
        catchError(buildResult: 'FAILURE', stageResult: 'FAILURE') {
          sh 'chmod +x frontend/ci-checks && ./frontend/ci-checks test'
          script { env.PASSED_FRONTEND = env.GIT_COMMIT }
        }
      }
    }

    stage('RAG: static validation') {
      when {
        allOf {
          not { branch 'master' }
          environment name: 'RUN_RAG', value: 'true'
        }
      }
      agent {
        docker { image 'python:3.12-slim' }
      }
      steps {
        // 여기서 실패해도 뒤 단계는 계속 돈다. 한 번의 파이프라인으로 모든
        // 실패를 보기 위해서다. 빌드 결과는 그대로 FAILURE 로 남는다.
        catchError(buildResult: 'FAILURE', stageResult: 'FAILURE') {
          sh 'chmod +x RAG/ci-checks && ./RAG/ci-checks test'
          script { env.TESTED_RAG = env.GIT_COMMIT }
        }
      }
    }

    stage('Infra: static validation') {
      when {
        allOf {
          not { branch 'master' }
          environment name: 'RUN_INFRA', value: 'true'
        }
      }
      agent any
      steps {
        // 여기서 실패해도 뒤 단계는 계속 돈다. 한 번의 파이프라인으로 모든
        // 실패를 보기 위해서다. 빌드 결과는 그대로 FAILURE 로 남는다.
        catchError(buildResult: 'FAILURE', stageResult: 'FAILURE') {
          sh '''
            test -x ops/deploy-jobis-container
            # 실행 비트가 빠지면 배포가 시작 직후 "not executable" 로 멈춘다.
            test -x ops/verify-jobis-release
          test -x ops/smoke-compose
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
          bash -n ops/smoke-compose
            git diff --check HEAD^ HEAD

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
        script { env.PASSED_INFRA = env.GIT_COMMIT }
        }
      }
    }


    // 정적분석. 검사 내용은 각 영역의 ci-checks 가 정하고 이 단계는 호출만 한다.
    // ruff(AI·RAG)는 지적 0건을 달성해 required 다. SpotBugs·ESLint 는 아직
    // advisory 이며, 승격 조건은 ops/CI_OWNERSHIP.md 에 적혀 있다.
    stage('backend: spotbugs') {
      when {
        allOf {
          not { branch 'master' }
          environment name: 'RUN_BACKEND', value: 'true'
        }
      }
      agent { docker { image 'eclipse-temurin:17-jdk' } }
      steps {
        catchError(buildResult: 'UNSTABLE', stageResult: 'UNSTABLE') {
          sh 'chmod +x backend/ci-checks && ./backend/ci-checks lint'
        }
      }
    }
    stage('frontend: eslint') {
      when {
        allOf {
          not { branch 'master' }
          environment name: 'RUN_FRONTEND', value: 'true'
        }
      }
      agent { docker { image 'node:22-alpine' } }
      steps {
        catchError(buildResult: 'UNSTABLE', stageResult: 'UNSTABLE') {
          sh 'chmod +x frontend/ci-checks && ./frontend/ci-checks lint'
        }
      }
    }
    stage('AI: ruff') {
      when {
        allOf {
          not { branch 'master' }
          environment name: 'RUN_AI', value: 'true'
        }
      }
      agent { docker { image 'python:3.11-slim' } }
      steps {
        catchError(buildResult: 'FAILURE', stageResult: 'FAILURE') {
          // 테스트와 required Ruff가 모두 통과한 커밋만 다음 빌드의 캐시에 남긴다.
          sh 'chmod +x AI/ci-checks && ./AI/ci-checks lint'
          script {
            if (env.TESTED_AI == env.GIT_COMMIT) {
              env.PASSED_AI = env.GIT_COMMIT
            }
          }
        }
      }
    }
    stage('RAG: ruff') {
      when {
        allOf {
          not { branch 'master' }
          environment name: 'RUN_RAG', value: 'true'
        }
      }
      agent { docker { image 'python:3.12-slim' } }
      steps {
        catchError(buildResult: 'FAILURE', stageResult: 'FAILURE') {
          // 테스트와 required Ruff가 모두 통과한 커밋만 다음 빌드의 캐시에 남긴다.
          sh 'chmod +x RAG/ci-checks && ./RAG/ci-checks lint'
          script {
            if (env.TESTED_RAG == env.GIT_COMMIT) {
              env.PASSED_RAG = env.GIT_COMMIT
            }
          }
        }
      }
    }

    // 서비스 CI 는 항상 **빈** PostgreSQL 에서 마이그레이션을 검증한다. 빈 DB 에는 적용 이력이
    // 없으므로 "이미 적용된 버전과 어긋난다"는 결함이 구조적으로 걸리지 않는다.
    // 실측(2026-08-08): 통합 브랜치가 운영에 이미 적용된 V20~V28 을 삭제·재번호했는데
    // develop CI 는 끝까지 초록이었고, master #9 배포에서 backend 가 기동하지 못해 롤백됐다.
    //
    // develop 에 두는 이유:
    //   - 여기가 통합 게이트다. master 는 검증된 develop 트리를 승격만 한다
    //     ('Master release: verify' 가 트리 동일성을 강제하므로 검증이 약해지지 않는다).
    //   - master 에서 걸리면 이미 develop->master 머지를 되돌려야 한다. 여기가 훨씬 싸다.
    //   - 이미지 빌드 앞에 둬서, 실패하면 여섯 이미지 빌드 비용을 쓰지 않는다.
    //
    // 운영 DB 는 읽지도 쓰지도 않는다. 덤프를 일회용 컨테이너에 복원해서만 검사한다.
    // JOBIS_BACKUP_DIR 는 Jenkins 전역 환경변수로 설정한다(DEPLOY_HOST 와 같은 방식).
    stage('Release migration gate') {
      when { branch 'develop' }
      agent any
      steps {
        sh '''
          set -euo pipefail
          test -n "${JOBIS_BACKUP_DIR:-}" || {
            echo "JOBIS_BACKUP_DIR 전역 환경변수가 없습니다." >&2
            exit 1
          }
          # 덤프는 root 소유 0600 이고 백업 디렉터리는 Jenkins 컨테이너에 없다. 스크립트가
          # 형제 컨테이너로만 접근하며, 워크스페이스는 Jenkins 볼륨을 공유해서 넘긴다
          # (Infra 스테이지의 --volumes-from 과 같은 이유).
          JOBIS_JENKINS_CONTAINER="$(cat /etc/hostname)" \
          JOBIS_WORKSPACE="$WORKSPACE" \
            bash ops/test-release-migrations backend/src/main/resources/db/migration
        '''
      }
    }

    // develop에서 임시 ci-<SHA> 태그로 이미지를 만든다. 불변 SHA 태그는 smoke가
    // 통과한 뒤에만 발행해 실패한 이미지가 master 승격 후보가 되지 않게 한다.
    stage('Docker images: build') {
      when {
        allOf {
          branch 'develop'
          expression {
            currentBuild.result == null || currentBuild.result == 'SUCCESS' ||
              currentBuild.result == 'UNSTABLE'
          }
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
            tag="ci-$GIT_COMMIT"
            docker build -t "${prefix}jobis-backend:$tag" backend
            docker build -t "${prefix}jobis-ai:$tag" AI
            docker build -t "${prefix}jobis-frontend:$tag" frontend
            docker build -t "${prefix}jobis-rag-search:$tag" \
              -f infra/airflow/Dockerfile.rag-search .
            docker build -t "${prefix}jobis-rag-ingest:$tag" \
              -f infra/airflow/Dockerfile.rag-ingest .
            docker build -t "${prefix}jobis-airflow:$tag" \
              -f infra/airflow/Dockerfile.airflow .
          '''
        }
      }
    }

    // develop 통합 게이트. 각 영역은 자기 안에서만 검증됐다. 여기서는 방금 빌드한
    // 이미지를 그대로 띄워 접합부(nginx→백엔드→DB, 백엔드→AI)가 붙는지 본다.
    // 운영이 '처음 실행되는 곳'이 되지 않게 하는 최소 장치다.
    stage('Compose smoke (develop)') {
      when {
        allOf {
          branch 'develop'
          expression {
            currentBuild.result == null || currentBuild.result == 'SUCCESS' ||
              currentBuild.result == 'UNSTABLE'
          }
        }
      }
      agent any
      steps {
        script {
          // Jenkins 컨테이너의 Docker CLI 에는 Compose 플러그인이 없을 수 있다.
          // Compose 가 포함된 공식 CLI 이미지에서 돌리고, 워크스페이스는
          // --volumes-from 으로 넘긴다(호스트 데몬에는 $WORKSPACE 경로가 없다).
          def jenkinsContainer = sh(script: 'cat /etc/hostname', returnStdout: true).trim()
          // --volumes-from 은 CLI 컨테이너가 워크스페이스를 보게 해줄 뿐이다. 그 안에서
          // compose 가 띄우는 컨테이너의 바인드 마운트는 **호스트 데몬**이 경로 문자열로
          // 푸는데, $WORKSPACE 는 호스트에 없는 경로다. 데몬은 없는 경로를 빈 디렉터리로
          // 만들어 마운트하므로 postgres 초기화 스크립트가 사라지고, V1 이
          // `role "jobiss_app" does not exist` 로 죽는다(실측 2026-08-09 develop #45).
          // jenkins_home 바인드의 호스트 경로로 접두사를 갈아 호스트 기준 경로를 만든다.
          // inspect 실패를 치명적으로 두지 않는다. Jenkins 가 컨테이너가 아니면
          // /etc/hostname 은 조회할 컨테이너 이름이 아니므로 실패가 정상이고,
          // 그 환경에서는 컨테이너 경로 == 호스트 경로라 아래 fallback 이 맞다.
          def homeSource = sh(
            script: "docker inspect ${jenkinsContainer} " +
              "--format '{{range .Mounts}}{{if eq .Destination \"/var/jenkins_home\"}}{{.Source}}{{end}}{{end}}' " +
              "2>/dev/null || true",
            returnStdout: true
          ).trim()
          def hostRoot = env.WORKSPACE
          if (homeSource && env.WORKSPACE.startsWith('/var/jenkins_home/')) {
            hostRoot = homeSource + env.WORKSPACE.substring('/var/jenkins_home'.length())
          } else {
            // 컨테이너 밖에서 도는 Jenkins 이거나 워크스페이스가 jenkins_home 밖에 있다.
            // 그 경우 컨테이너 경로 == 호스트 경로이므로 그대로 쓴다. 틀렸다면
            // ops/smoke-compose 의 선제 검사가 원인을 명시하며 멈춘다.
            echo "[smoke] jenkins_home 바인드를 찾지 못해 WORKSPACE 를 호스트 경로로 쓴다."
          }
          sh """
            docker run --rm \
              --volumes-from "${jenkinsContainer}" \
              -v /var/run/docker.sock:/var/run/docker.sock \
              -w "\$WORKSPACE" \
              -e SMOKE_IMAGE_TAG="ci-\$GIT_COMMIT" \
              -e SMOKE_IMAGE_PREFIX="\${JOBIS_IMAGE_PREFIX:-}" \
              -e SMOKE_HOST_ROOT="${hostRoot}" \
              docker:28-cli \
              sh -ec 'apk add --no-cache bash >/dev/null && chmod +x ops/smoke-compose && bash ops/smoke-compose'
          """
        }
      }
    }

    stage('Docker images: publish') {
      when {
        allOf {
          branch 'develop'
          expression {
            currentBuild.result == null || currentBuild.result == 'SUCCESS' ||
              currentBuild.result == 'UNSTABLE'
          }
        }
      }
      agent any
      steps {
        script {
          sh '''
            set -euo pipefail
            prefix="${JOBIS_IMAGE_PREFIX:-}"
            for image in jobis-backend jobis-ai jobis-frontend \
                         jobis-rag-search jobis-rag-ingest jobis-airflow; do
              source="${prefix}${image}:ci-$GIT_COMMIT"
              target="${prefix}${image}:$GIT_COMMIT"
              docker image inspect "$source" >/dev/null
              docker tag "$source" "$target"
            done
          '''

          if (env.JOBIS_IMAGE_PREFIX?.trim()) {
            withCredentials([usernamePassword(
              credentialsId: 'jobis-container-registry',
              usernameVariable: 'REGISTRY_USER',
              passwordVariable: 'REGISTRY_PASSWORD'
            )]) {
              sh '''
                set -euo pipefail
                registry="${JOBIS_IMAGE_PREFIX%%/*}"
                printf '%s' "$REGISTRY_PASSWORD" | docker login "$registry" \
                  --username "$REGISTRY_USER" --password-stdin
                trap 'docker logout "$registry" >/dev/null 2>&1 || true' EXIT
                for image in jobis-backend jobis-ai jobis-frontend \
                             jobis-rag-search jobis-rag-ingest jobis-airflow; do
                  docker push "${JOBIS_IMAGE_PREFIX}${image}:$GIT_COMMIT"
                done
              '''
            }
          } else {
            echo 'Smoke-tested SHA images are ready on the shared Docker daemon.'
          }
        }
      }
    }

    stage('Docker images: promote') {
      when {
        allOf {
          branch 'master'
          expression { currentBuild.result == null || currentBuild.result == 'SUCCESS' }
        }
      }
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

    stage('Deploy production') {
      when {
        allOf {
          branch 'master'
          expression { currentBuild.result == null || currentBuild.result == 'SUCCESS' }
        }
      }
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

  // 선언형 파이프라인은 post 섹션을 하나만 허용한다.
  post {
    always {
      script {
        // 영역별 '마지막으로 통과한 커밋'을 다음 빌드가 읽을 수 있게 남긴다.
        // 이번에 돌지 않았거나 실패한 영역은 이전 기록을 그대로 물려받는다.
        // 정규식 Matcher 는 CPS 에서 직렬화되지 않으므로 문자열 연산만 쓴다.
        def memo = env.CI_PASS_MEMO ?: ''
        def areas = ['backend', 'ai', 'frontend', 'rag', 'infra']
        def passed = [env.PASSED_BACKEND, env.PASSED_AI, env.PASSED_FRONTEND,
                      env.PASSED_RAG, env.PASSED_INFRA]
        def out = ''
        for (int i = 0; i < areas.size(); i++) {
          def sha = passed[i]
          if (!sha) {
            def key = areas[i] + '='
            def at = memo.indexOf(key)
            if (at >= 0) {
              def rest = memo.substring(at + key.length())
              def sp = rest.indexOf(' ')
              sha = (sp < 0) ? rest : rest.substring(0, sp)
            }
          }
          if (sha) {
            out = out + ' ' + areas[i] + '=' + sha
          }
        }
        if (out) {
          currentBuild.description = 'ci-pass:' + out
        }
      }
    }
    // GitLab 에 최종 상태를 직접 보고한다. UNSTABLE 은 플러그인이 매핑하지 않아
    // MR 상태가 running 에 머물렀다. advisory 는 머지를 막지 않으므로 success 다.
    success { updateGitlabCommitStatus name: 'jenkins', state: 'success' }
    unstable { updateGitlabCommitStatus name: 'jenkins', state: 'success' }
    failure { updateGitlabCommitStatus name: 'jenkins', state: 'failed' }
    aborted { updateGitlabCommitStatus name: 'jenkins', state: 'canceled' }
  }
}
