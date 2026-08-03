// JOBIS Jenkins CI/CD
//
//   모든 브랜치 push/MR : CI (backend 테스트 + fake-ai 스모크 테스트)
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
    timeout(time: 30, unit: 'MINUTES')
    gitLabConnection('ssafy-gitlab')   // 빌드 상태를 GitLab 커밋/MR에 보고
  }

  stages {

    stage('Backend: test & package') {
      agent any
      steps {
        updateGitlabCommitStatus name: 'jenkins', state: 'running'
        script {
          // 운영 DB가 PostgreSQL이므로 CI도 동일한 DB로 테스트한다 (방언 불일치 방지)
          docker.image('postgres:16').withRun(
            '-e POSTGRES_DB=jobiss ' +
            '-e POSTGRES_USER=jobis_ci ' +
            '-e POSTGRES_PASSWORD=ci-only-password'
          ) { db ->
            docker.image('eclipse-temurin:17-jdk').inside("--link ${db.id}:postgres") {
              withEnv([
                'DB_URL=jdbc:postgresql://postgres:5432/jobiss',
                'DB_USERNAME=jobis_ci',
                'DB_PASSWORD=ci-only-password',
                'JWT_SECRET=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef'
              ]) {
              sh '''
                # PostgreSQL 기동 대기
                bash -c 'for i in $(seq 1 30); do (echo > /dev/tcp/postgres/5432) 2>/dev/null && exit 0; sleep 2; done; echo "PostgreSQL not ready"; exit 1'
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

    stage('fake-ai: test & package') {
      agent {
        docker { image 'node:24' }
      }
      steps {
        sh '''
          cd fake-ai
          npm ci --omit=dev --ignore-scripts
          node --check server.js
          node --check llm.js
          node --check providers/index.js
          node --check providers/codex.js
          node --check providers/codex-sidecar.js
          npm test

          # 스모크 테스트: CI에서는 실제 Claude/Codex를 호출하지 않고 /extract 계약만 확인
          LLM_PROVIDER=claude LLM_DISABLED=1 node server.js > /tmp/fake-ai.log 2>&1 &
          pid=$!
          ready=false
          for i in $(seq 1 20); do
            if curl -fsS -X POST -H 'Content-Type: application/json' \
              -d '{"sourceType":"TEXT","content":"Java Spring Boot MySQL"}' \
              http://127.0.0.1:8000/extract >/dev/null 2>&1; then
              ready=true; break
            fi
            sleep 1
          done
          kill "$pid" 2>/dev/null || true
          [ "$ready" = true ] || { cat /tmp/fake-ai.log; exit 1; }

          tar -czf fake-ai.tar.gz \
            package.json package-lock.json server.js llm.js result.json \
            README.md NOTICE pyproject.toml uv.lock codex_oauth_adapter providers node_modules
        '''
        stash name: 'fake-ai-tar', includes: 'fake-ai/fake-ai.tar.gz'
      }
    }

    stage('RAG: static validation') {
      agent {
        docker { image 'python:3.11-slim' }
      }
      steps {
        sh '''
          python -m compileall -q RAG
          python -m unittest discover -s RAG/tests -v
        '''
      }
    }

    // 도커 전환 2단계: 배포 이미지를 CI에서 빌드해 쌓아둔다 (ops/DOCKER.md 참고).
    // Jenkins가 호스트 도커 데몬을 쓰므로(DooD) 빌드된 이미지는 곧바로 배포 서버에 존재한다.
    // 아직 컨테이너로 서비스하지는 않는다 — 기존 jar/systemd 배포(아래 스테이지)와 병행.
    stage('Docker images: build') {
      when { branch 'master' }
      agent any
      steps {
        sh '''
          docker build -t "jobis-backend:$GIT_COMMIT" backend
          docker build -t "jobis-fake-ai:$GIT_COMMIT" fake-ai

          # 오래된 이미지 태그 정리: 최근 3개만 유지.
          # 내용이 같은 이미지는 CreatedAt이 동일해 정렬이 태그 문자열로 갈리므로,
          # 방금 빌드한 $GIT_COMMIT 태그는 나이와 무관하게 절대 지우지 않는다 (deploy-jobis의 링크 보호와 동일한 원칙)
          for img in jobis-backend jobis-fake-ai; do
            docker images --format '{{.CreatedAt}}\t{{.Tag}}' "$img" \
              | grep -v '<none>' | sort -r | awk -F'\t' 'NR>3{print $2}' \
              | while read -r tag; do
                  [ "$tag" = "$GIT_COMMIT" ] && continue
                  docker image rm "$img:$tag" || true
                done
          done
        '''
      }
    }

    stage('Deploy production') {
      when { branch 'master' }
      agent any
      steps {
        unstash 'backend-jar'
        unstash 'fake-ai-tar'
        sshagent(credentials: ['jobis-deploy-ssh']) {
          sh '''
            test -n "$DEPLOY_HOST" || { echo "DEPLOY_HOST 전역 환경변수가 없습니다."; exit 1; }
            scp -o StrictHostKeyChecking=accept-new \
              backend/backend.jar \
              "jobis-deploy@$DEPLOY_HOST:/tmp/jobis-backend-$GIT_COMMIT.jar"
            scp -o StrictHostKeyChecking=accept-new \
              fake-ai/fake-ai.tar.gz \
              "jobis-deploy@$DEPLOY_HOST:/tmp/jobis-fake-ai-$GIT_COMMIT.tar.gz"
            ssh -o StrictHostKeyChecking=accept-new \
              "jobis-deploy@$DEPLOY_HOST" \
              "sudo -n /usr/local/sbin/deploy-jobis '$GIT_COMMIT'"
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
