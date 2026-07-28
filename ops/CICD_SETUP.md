# JOBIS GitLab CI/CD 초기 설정

`.gitlab-ci.yml`을 처음 동작시키기 전에 한 번만 수행할 서버·GitLab 설정을 설명합니다.

## 파이프라인 구조

| 트리거 | 실행 내용 |
|---|---|
| MR 생성·갱신 | CI (backend 테스트 + fake-ai 스모크 테스트) |
| `develop` push(병합) | CI만 실행, 배포 없음 |
| `master` push(병합) | CI 통과 후 운영 서버 자동 배포 |

배포 단계 동작 순서:

1. MySQL 8 서비스 컨테이너로 Spring Boot 테스트 및 실행 JAR 생성
2. fake-ai 의존성 설치, `/extract` 스모크 테스트, 배포 아카이브 생성
3. JAR와 fake-ai 아카이브를 배포 서버 `/tmp`에 업로드
4. 서버의 고정 명령 `/usr/local/sbin/deploy-jobis` 실행 (심볼릭 링크 교체)
5. 두 systemd 서비스 재시작 후 `/extract`, `/health` 헬스체크
6. 실패 시 이전 릴리스로 자동 롤백

운영 DB와 JWT 값은 계속 서버의 `/etc/jobis/jobis.env`에만 보관합니다.
GitLab CI/CD 변수에는 DB·JWT 운영 비밀값을 등록하지 않습니다.

---

## A. 서버 사전 설정 (관리자, 1회)

### 1. fake-ai 서비스 경로를 심볼릭 링크로 전환

```bash
sudo ln -sfn /opt/jobis/fake-ai /opt/jobis/fake-ai-current
```

`/etc/systemd/system/jobis-fake-ai.service`의 실행 경로 변경:

```ini
[Service]
User=ubuntu
WorkingDirectory=/opt/jobis/fake-ai-current
Environment=NODE_ENV=production
ExecStart=/usr/bin/node /opt/jobis/fake-ai-current/server.js
Restart=on-failure
RestartSec=5
```

```bash
sudo systemctl daemon-reload
sudo systemctl restart jobis-fake-ai
```

### 2. 배포 명령 설치

저장소의 `ops/deploy-jobis`를 서버로 전송한 뒤:

```bash
sudo install -o root -g root -m 0755 /tmp/deploy-jobis /usr/local/sbin/deploy-jobis
```

### 3. 배포 전용 SSH 사용자·키 생성

관리자 키를 재사용하지 않고 CI 전용 키를 만듭니다.

```bash
# 로컬에서
ssh-keygen -t ed25519 -C "gitlab-ci-jobis" -f jobis-deploy
```

```bash
# 서버에서
sudo adduser --disabled-password --gecos "" jobis-deploy
sudo install -d -o jobis-deploy -g jobis-deploy -m 0700 /home/jobis-deploy/.ssh
# jobis-deploy.pub 내용을 아래 파일에 한 줄로 추가
sudo nano /home/jobis-deploy/.ssh/authorized_keys
sudo chown jobis-deploy:jobis-deploy /home/jobis-deploy/.ssh/authorized_keys
sudo chmod 600 /home/jobis-deploy/.ssh/authorized_keys
```

### 4. 배포 명령만 sudo 허용

```bash
sudo visudo -f /etc/sudoers.d/jobis-deploy
```

```text
jobis-deploy ALL=(root) NOPASSWD: /usr/local/sbin/deploy-jobis *
```

### 5. known_hosts 값 준비

로컬에서 실행한 결과를 복사해 둡니다. (GitLab 변수로 등록할 값)

```bash
ssh-keyscan -H 서버주소
```

---

## B. GitLab 설정 (Maintainer, 1회)

### 1. CI/CD 변수 등록

`Settings → CI/CD → Variables → Add variable`에서 4개를 등록합니다.

| Key | Type | 값 | Flags |
|---|---|---|---|
| `DEPLOY_HOST` | Variable | 배포 서버 주소 | **Protected** |
| `DEPLOY_USER` | Variable | `jobis-deploy` | **Protected** |
| `DEPLOY_SSH_KEY` | **File** | `jobis-deploy` 개인키 전체 내용 | **Protected** |
| `DEPLOY_KNOWN_HOSTS` | **File** | `ssh-keyscan -H 서버주소` 결과 | **Protected** |

- `DEPLOY_SSH_KEY`와 `DEPLOY_KNOWN_HOSTS`는 여러 줄이므로 반드시 **Type: File**로 등록합니다.
- 전부 **Protected** 플래그를 켭니다. → Protected 브랜치(master)의 파이프라인에서만 노출되어, 팀원이 feature 브랜치 CI에서 키를 읽어갈 수 없습니다.

### 2. Protected Branch 확인

`Settings → Repository → Protected branches`에서 `master`가 보호되어 있는지 확인합니다.
(Protected 변수는 보호 브랜치에서만 주입되므로, master가 미보호 상태면 배포 잡이 변수를 못 받아 실패합니다.)

### 3. Runner 확인

`Settings → CI/CD → Runners`에서 사용 가능한 Runner(공용 Runner)가 활성화되어 있는지 확인합니다.
SSAFY GitLab은 공용 Runner를 제공하므로 별도 설치는 보통 불필요합니다.

### 4. 파이프라인 확인

- MR을 만들면 `backend-test`, `fake-ai-test` 두 잡이 실행됩니다.
- `master`에 병합되면 `deploy-production` 잡이 추가로 실행됩니다.
- 실행 이력: `Build → Pipelines`, 배포 이력: `Operate → Environments → production`

---

## 문제 해결

| 증상 | 원인 |
|---|---|
| deploy 잡에서 "변수가 없습니다" | 변수 미등록 또는 Protected 플래그와 브랜치 보호 상태 불일치 |
| `Permission denied (publickey)` | 서버 `authorized_keys` 등록 누락, 키 불일치 |
| `Host key verification failed` | `DEPLOY_KNOWN_HOSTS` 값 오류 (`ssh-keyscan -H` 재실행) |
| `sudo: a password is required` | `/etc/sudoers.d/jobis-deploy` 설정 누락 |
| 헬스체크 실패 후 롤백 | 서버 로그 확인: `journalctl -u jobis -u jobis-fake-ai -n 100` |
