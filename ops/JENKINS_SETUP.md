# JOBIS Jenkins CI/CD 초기 설정

`Jenkinsfile`을 처음 동작시키기 전에 한 번만 수행할 설정입니다.
서버 쪽 사전 작업(배포 사용자, deploy-jobis 설치, systemd 전환)은 [CICD_SETUP.md](CICD_SETUP.md) A절과 동일합니다.

## 파이프라인 구조

| 트리거 | 실행 |
|---|---|
| 모든 브랜치 push (feat/develop/master) | CI: backend 테스트 + fake-ai 스모크 테스트 |
| `master` push(=MR 병합) | CI 통과 후 운영 서버 자동 배포 |

MR 단계의 CI는 소스 브랜치 push 시점에 이미 실행되므로, MR을 만들기 전에 push만 하면 결과를 확인할 수 있습니다.

---

## 1. Jenkins 컨테이너 요구사항

파이프라인이 도커 이미지(temurin, node, mysql)로 빌드하므로 Jenkins 컨테이너가 호스트 도커를 쓸 수 있어야 합니다.

```bash
docker run -d --name jenkins \
  -p 8081:8080 \
  -v jenkins_home:/var/jenkins_home \
  -v /var/run/docker.sock:/var/run/docker.sock \
  jenkins/jenkins:lts-jdk17
```

컨테이너 안에 docker CLI가 없으면 설치합니다.

```bash
docker exec -u root jenkins bash -c "apt-get update && apt-get install -y docker.io"
# docker.sock 권한 (컨테이너 재시작 시에도 유지되도록 그룹 매핑 권장)
docker exec -u root jenkins chmod 666 /var/run/docker.sock
```

> 이미 nginx + https 뒤에 Jenkins가 떠 있다면 `-v /var/run/docker.sock:...` 마운트와
> docker CLI 설치 여부만 확인하면 됩니다.

## 2. 플러그인 설치

`Manage Jenkins → Plugins → Available`에서:

- **Docker Pipeline** (docker.image().inside 지원)
- **SSH Agent** (배포 SSH 키 사용)
- **JUnit** (테스트 리포트, 보통 기본 설치됨)
- **GitLab** (선택 — MR 화면에 빌드 상태 표시용)

## 3. 자격증명 등록

`Manage Jenkins → Credentials → System → Global credentials → Add Credentials`

| 항목 | 값 |
|---|---|
| Kind | SSH Username with private key |
| ID | `jobis-deploy-ssh` (Jenkinsfile과 일치해야 함) |
| Username | `jobis-deploy` |
| Private Key | 배포 전용 개인키 붙여넣기 |

GitLab 저장소 접근용 자격증명도 하나 등록합니다 (Username/Password — GitLab 계정 또는 Access Token).

## 4. 전역 환경변수

`Manage Jenkins → System → Global properties → Environment variables`

| Name | Value |
|---|---|
| `DEPLOY_HOST` | 배포 서버 주소. Jenkins가 배포 서버 자신이라면 도커 브리지 게이트웨이 `172.17.0.1` |

## 5. Multibranch Pipeline 잡 생성

1. `New Item → Multibranch Pipeline`, 이름: `jobis`
2. **Branch Sources → Add source → Git**
   - Repository URL: `https://lab.ssafy.com/s15-webmobile1-sub1/S15P11C202.git`
   - Credentials: 3번에서 만든 GitLab 자격증명
3. **Build Configuration**: by Jenkinsfile (기본값, 경로 `Jenkinsfile`)
4. 저장 → 자동으로 브랜치 스캔 후 브랜치별 잡 생성

## 6. GitLab 웹훅 연결 (push 즉시 빌드)

GitLab에서: `Settings → Webhooks → Add new webhook`

- URL: `https://젠킨스주소/multibranch-webhook-trigger/invoke?token=jobis`
  (간단하게는 `https://젠킨스주소/git/notifyCommit?url=https://lab.ssafy.com/s15-webmobile1-sub1/S15P11C202.git`)
- Trigger: **Push events**, **Merge request events**

웹훅 없이도 Multibranch 잡의 `Scan Multibranch Pipeline Triggers → Periodically`(예: 5분)로 폴링할 수 있습니다.
웹훅 방식이 안 잡히면 우선 폴링으로 시작하는 것이 간단합니다.

## 7. 확인

1. feat 브랜치 push → Jenkins `jobis` 잡에 브랜치가 나타나고 CI 2개 스테이지 실행
2. develop 병합 → develop 브랜치 잡에서 CI 실행 (배포 스테이지는 skip)
3. master 병합 → CI + `Deploy production` 스테이지 실행 → 서비스 반영

## 문제 해결

| 증상 | 원인 |
|---|---|
| `docker: not found` | Jenkins 컨테이너에 docker CLI 미설치 또는 docker.sock 미마운트 |
| `Permission denied` (docker.sock) | sock 권한 — 1번 참고 |
| `Host key verification failed` | 첫 접속 — Jenkinsfile은 `accept-new`라 재실행하면 해결 |
| `sudo: a password is required` | 서버 sudoers 설정 누락 (CICD_SETUP.md A-4절) |
| 배포 실패 후 이전 버전으로 복귀됨 | 정상 (자동 롤백). 서버 로그: `journalctl -u jobis -u jobis-fake-ai -n 100` |
