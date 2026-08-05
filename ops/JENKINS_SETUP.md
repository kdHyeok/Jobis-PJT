# JOBISS Jenkins 설정

Jenkins는 Multibranch Pipeline으로 저장소의 `Jenkinsfile`을 실행한다.

## 필수 조건

- Linux agent, Java 17, Docker Engine, Docker CLI와 Compose plugin, `flock`
- Jenkins plugin: Docker Pipeline, SSH Agent, JUnit, GitLab
- GitLab connection: `ssafy-gitlab`
- SSH credential: `jobis-deploy-ssh`
- Secret file credential: `jobis-deploy-known-hosts` (배포 서버의 검증된 SSH host key)
- 전역 환경 변수: `DEPLOY_HOST`

Docker socket 접근은 호스트 root와 동등한 권한이다. 전용 agent를 사용하고 socket을
`chmod 666`으로 열지 말며, Docker 그룹과 Jenkins agent 그룹을 명시적으로 맞춘다.

## 이미지 전달 방식

Jenkins와 배포 서버가 다른 Docker daemon이면 registry를 사용해야 한다.

1. 전역 환경 변수 `JOBIS_IMAGE_PREFIX`에 trailing slash를 포함한 경로를 설정한다.
   예: `registry.example.com/group/project/`
2. username/password credential `jobis-container-registry`를 만든다. 최소 push/pull 권한의
   deploy token이나 robot account를 사용한다.
3. 배포 서버에서 root Docker 사용자로 같은 registry에 한 번 로그인한다.

```bash
sudo docker login registry.example.com
```

비밀번호나 token은 Jenkinsfile, 저장소, 셸 명령 기록에 넣지 않는다. 배포 서버가 registry
인증 정보를 잃으면 새 배포의 `docker compose pull`이 서비스 중지 전에 실패하므로 기존
서비스는 계속 유지된다.

Jenkins와 배포 서버가 실제로 같은 Docker daemon을 사용할 때만
`JOBIS_IMAGE_PREFIX`를 비워 둘 수 있다. 이 경우 credential과 push/pull은 생략된다.

## 브랜치 게이트

- 기능 브랜치와 MR: Backend, AI v2bridge, Frontend, RAG, Infra CI
- `develop`: 전체 CI + 여섯 SHA 이미지 build/push, 운영 배포 없음
- `master`: develop 부모·동일 트리 검증 + 검증된 여섯 이미지의 master SHA 승격 + 자동 CD
- `master` 직접 push 금지, protected branch와 `develop -> master` release MR만 허용
- 운영 배포 credential과 환경 변수는 protected branch에서만 사용 가능

`master`에서는 동일 소스에 대한 전체 테스트와 Docker build를 반복하지 않는다. 대신 merge commit의
두 번째 부모가 `origin/develop` 이력에 포함되고 master 결과 트리가 그 부모와 완전히 같은지 검사한다.
동일 Docker daemon 구성은 develop SHA 이미지를 master SHA로 retag하고, registry 구성은 develop SHA를
pull한 뒤 master SHA로 push한다. 검증된 develop 이미지가 없거나 트리가 달라지면 배포 전에 실패한다.

Jenkins는 CD에서 서버에 SSH로 접속해 다음 명령만 실행한다.

```bash
sudo -n /usr/local/sbin/deploy-jobis '<40자리 GIT_COMMIT>'
```

`known_hosts`는 배포 서버 콘솔에서 확인한 fingerprint와 대조한 뒤 Jenkins Secret file로
등록한다. 네트워크에서 처음 보이는 키를 그대로 수락하지 않는다. master CD는 릴리스마다
Compose, 운영 스크립트와 jobrag Flyway 파일을 먼저 동기화한 다음 감사를 실행한다.

서버 설치, 백업, 복원 훈련, smoke test는 [DEPLOYMENT.md](DEPLOYMENT.md)를 따른다.
