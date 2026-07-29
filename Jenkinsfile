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
          docker.image('mysql:8.0').withRun(
            '-e MYSQL_DATABASE=jobiss ' +
            '-e MYSQL_USER=jobis_ci ' +
            '-e MYSQL_PASSWORD=ci-only-password ' +
            '-e MYSQL_ROOT_PASSWORD=ci-only-root-password'
          ) { db ->
            docker.image('eclipse-temurin:17-jdk').inside("--link ${db.id}:mysql") {
              withEnv([
                'DB_URL=jdbc:mysql://mysql:3306/jobiss?useSSL=false&allowPublicKeyRetrieval=true&serverTimezone=UTC',
                'DB_USERNAME=jobis_ci',
                'DB_PASSWORD=ci-only-password',
                'JWT_SECRET=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef'
              ]) {
              sh '''
                # MySQL 기동 대기
                bash -c 'for i in $(seq 1 30); do (echo > /dev/tcp/mysql/3306) 2>/dev/null && exit 0; sleep 2; done; echo "MySQL not ready"; exit 1'
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

          # 스모크 테스트: /extract 응답 확인
          node server.js > /tmp/fake-ai.log 2>&1 &
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

          tar -czf fake-ai.tar.gz package.json package-lock.json server.js result.json node_modules
        '''
        stash name: 'fake-ai-tar', includes: 'fake-ai/fake-ai.tar.gz'
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
