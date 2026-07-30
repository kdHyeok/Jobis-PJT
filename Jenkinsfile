// JOBIS Jenkins CI/CD
//
//   모든 브랜치 push/MR : CI (backend + fake-ai + RAG + 배포 파일 정적 검증)
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

    stage('Infra: static validation') {
      agent any
      steps {
        sh '''
          test -x ops/deploy-jobis-container
          bash -n ops/deploy-jobis-container

          # Jenkins 컨테이너에는 운영 서버의 /etc/jobis/jobis.env가 없으므로
          # 절대 경로와 env_file 내용은 해석하지 않고 Compose 모델만 검증한다.
          # Jenkins 컨테이너의 Docker CLI에는 Compose 플러그인이 없을 수 있다.
          # Compose가 포함된 공식 CLI 이미지에 파일을 표준입력으로 전달해 모델만 검증한다.
          docker run --rm -i \
            -e JOBIS_SHA=0000000000000000000000000000000000000000 \
            docker:28-cli \
            sh -ec '
              mkdir -p /etc/jobis
              : > /etc/jobis/jobis.env
              exec docker compose --project-name jobis-validation -f - \
                config --quiet --no-path-resolution --no-env-resolution
            ' \
            < ops/docker-compose.prod.yml
        '''
      }
    }

    // 도커 전환 2단계: 배포 이미지를 CI에서 빌드해 쌓아둔다 (ops/DOCKER.md 참고).
    // Jenkins가 호스트 도커 데몬을 쓰므로(DooD) 빌드된 이미지는 곧바로 배포 서버에 존재한다.
    // 이미지 정리는 배포 성공 후 deploy-jobis가 현재·직전 SHA를 보호하며 수행한다.
    stage('Docker images: build') {
      when { branch 'master' }
      agent any
      steps {
        sh '''
          docker build -t "jobis-backend:$GIT_COMMIT" backend
          docker build -t "jobis-fake-ai:$GIT_COMMIT" fake-ai
        '''
      }
    }

    stage('Deploy production') {
      when { branch 'master' }
      agent any
      // 컨테이너 배포(3단계)부터는 전송할 산출물이 없다.
      // 위 스테이지가 호스트 도커 데몬에 이미지를 빌드했고(DooD), Jenkins와 배포 대상이
      // 같은 호스트이므로 SHA만 넘기면 deploy-jobis가 해당 태그로 컨테이너를 교체한다.
      steps {
        sshagent(credentials: ['jobis-deploy-ssh']) {
          sh '''
            test -n "$DEPLOY_HOST" || { echo "DEPLOY_HOST 전역 환경변수가 없습니다."; exit 1; }
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
