# 2. 외부 서비스 정보

프로젝트가 사용하는 외부 서비스와, 가입·발급·설정에 필요한 정보를 정리한다.
**모든 키는 `.env`(로컬) 또는 `/etc/jobis/jobis-v2.env`(운영)에만 넣고 Git에 올리지 않는다.**

## 0. 소셜 로그인 없음

이 프로젝트의 사용자 인증은 **자체 이메일·비밀번호 방식**이다(`auth_identities` 테이블,
BCrypt 해시 + 회전 refresh 토큰). 소셜 인증(OAuth 로그인) 공급자를 사용하지 않으므로
해당 항목의 가입 절차는 없다. 아래 GitHub·GitLab 연동은 **로그인이 아니라 사용자의 저장소를
읽어 커리어 근거를 수집하는 기능**이다.

## 1. LLM 공급자 (택 1, 필수)

`LLM_PROVIDER`로 하나를 고른다. 팀 표준은 `anthropic`이다(결정 D140, 2026-08-07).

### 1.1 Anthropic API — 팀 표준

| 항목 | 값 |
|---|---|
| 가입 | https://console.anthropic.com |
| 발급 | Console → API Keys → Create Key |
| 환경 변수 | `LLM_PROVIDER=anthropic`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` |
| 기본 모델 | `claude-haiku-4-5-20251001` (경량), 상위 티어는 sonnet/opus 계열 |
| 과금 | 토큰 종량제 |

CLI 기동 오버헤드가 없고, codex 실행 파일이 없는 PC에서도 동작한다는 이유로 표준이 되었다
(codex_cli 강제 시절 codex가 없는 PC의 전 LLM 호출이 `WinError 2`로 죽은 실측이 있다).

### 1.2 SSAFY GMS (OpenAI 호환 프록시)

| 항목 | 값 |
|---|---|
| 발급 | SSAFY에서 배포하는 GMS 키 |
| Base URL | `https://gms.ssafy.io/gmsapi/api.openai.com/v1` |
| 환경 변수 | `LLM_PROVIDER=openai`, `GMS_KEY`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_MODEL_LIGHT` |
| 기본 모델 | `gpt-4.1-mini` |
| 주의 | RAG 임베딩까지 GMS로 돌리면 키 한도를 빠르게 소진한다. 최초 재현은 로컬 모델로 한다 |

### 1.3 OpenAI Codex (OAuth device flow)

| 항목 | 값 |
|---|---|
| 가입 | Codex 사용 권한이 있는 OpenAI 계정 |
| 인증 | 디바이스 코드 방식. `https://auth.openai.com/codex/device`에서 일회용 코드 입력 |
| 환경 변수 | `LLM_PROVIDER=codex`, `CODEX_MODEL`, `CODEX_MODEL_LIGHT`, `CODEX_REASONING_EFFORT`, `CODEX_TIMEOUT_SEC` |
| 인증 상태 | 컨테이너 볼륨의 `/var/lib/jobis-ai/codex/auth.json` (내용을 출력·커밋하지 않는다) |
| 로그인 명령 | `docker compose run --rm --no-deps --entrypoint python ai -m jobis_ai.codex_oauth_adapter.cli --login` |
| 확인 | 같은 명령의 `--models`로 실제 API 접근까지 확인한다. `/health` 200만으로는 증명되지 않는다 |

### 1.4 Claude Code CLI (`claude_code`)

로컬 개발 반복용 보조 경로다. `CLAUDE_CODE_MODEL=sonnet`, `CLAUDE_CODE_MODEL_LIGHT=haiku`.
서버 배포에는 사용하지 않는다.

## 2. 공고 원문 추출 폴백 (선택, 없으면 해당 폴백만 건너뜀)

공고 URL의 본문이 JavaScript로 렌더되어 직접 HTML/iframe 수집이 실패했을 때만 호출한다.
`JOBIS_*_ENABLED=true`이고 키가 있을 때만 동작한다.

| 서비스 | 가입 | 환경 변수 |
|---|---|---|
| Jina Reader | https://jina.ai | `JOBIS_JINA_ENABLED`, `JINA_API_KEY` |
| Firecrawl | https://firecrawl.dev | `JOBIS_FIRECRAWL_ENABLED`, `FIRECRAWL_API_KEY` |
| Tavily | https://tavily.com | `JOBIS_TAVILY_ENABLED`, `TAVILY_API_KEY` |

세 서비스 모두 무료 티어가 있다. 키를 비워 두면 그 폴백만 비활성이고 직접 수집 경로는 그대로 동작한다.

## 3. NAVER CLOVA Studio (선택) — 이미지 공고 OCR/VLM

| 항목 | 값 |
|---|---|
| 가입 | https://clovastudio.ncloud.com (NAVER Cloud Platform 계정 필요) |
| 환경 변수 | `CLOVA_API_KEY`, `CLOVA_VLM_URL` |
| 기본 엔드포인트 | `https://clovastudio.stream.ntruss.com/v3/chat-completions/HCX-005` |
| 용도 | 이미지로 올라온 채용 공고의 텍스트 인식 |

## 4. 저장소 연동 (선택) — 커리어 근거 수집

사용자가 자기 GitHub/GitLab 저장소를 연결하면, 제출 시점의 실제 커밋과 선택된 코드 파일을
읽기 전용으로 수집해 역량 근거를 검증한다. 발급받은 토큰은 `REPOSITORY_TOKEN_ENCRYPTION_KEY`로
암호화해 저장한다(`RepositoryTokenCipher`).

구현 위치: `RepositoryConnectionController`(`/api/repository-connections`),
`RepositoryConnectionService`, `RepositoryEvidenceCollector`(GitHub/GitLab REST 실호출),
소비처는 `EvidenceService`·`EvidenceVerificationWorker`, 화면은 설정 → **코드 저장소 연결**.

> **로컬 Docker에서는 동작하지 않는다.** 루트 `compose.yaml`이 `GITHUB_APP_*`·`GITLAB_*`·
> `REPOSITORY_TOKEN_ENCRYPTION_KEY`를 backend 컨테이너로 전달하지 않는다(허용목록 방식).
> `.env`에 키를 채워도 연결 버튼을 누르면 서비스가 `GitHub App ID와 PKCS#8 개인 키가
> 설정되지 않았습니다` 같은 오류를 던진다. `env_file`을 쓰는 **운영 배포에서만 실사용
> 가능**하며, 로컬에서 쓰려면 `compose.yaml`에 전달을 추가하는 Infra 리뷰 MR이 필요하다.
> 같은 이유로 Redirect URI도 로컬에서는 애플리케이션 기본값
> `http://localhost:5473/app/settings`가 그대로 쓰인다.

### 4.1 GitHub App

| 항목 | 값 |
|---|---|
| 생성 | GitHub → Settings → Developer settings → GitHub Apps → New GitHub App |
| 권한 | Contents(읽기), Metadata(읽기) |
| 환경 변수 | `GITHUB_APP_ID`, `GITHUB_APP_SLUG`, `GITHUB_APP_PRIVATE_KEY`(PKCS#8), `GITHUB_APP_REDIRECT_URI`, `GITHUB_API_BASE_URL` |
| Redirect URI | 서비스 주소 + `/app/settings` (운영: `https://<도메인>/app/settings`) |
| API Base | `https://api.github.com` (GitHub Enterprise는 해당 주소) |

`GITHUB_APP_SLUG`가 비면 설치 URL을 만들 수 없어 연결 시작 단계에서 실패한다.

### 4.2 GitLab OAuth Application

| 항목 | 값 |
|---|---|
| 생성 | GitLab → User Settings → Applications |
| Scope | `read_api`, `read_repository` |
| 환경 변수 | `GITLAB_CLIENT_ID`, `GITLAB_CLIENT_SECRET`, `GITLAB_REDIRECT_URI`, `GITLAB_BASE_URL` |
| Redirect URI | 서비스 주소 + `/app/settings` |
| Base URL | `https://gitlab.com` 또는 `https://lab.ssafy.com` |

### 4.3 검증 범위

`RepositoryTokenCipherTest`(토큰 암복호화)만 자동 테스트가 있다. 실제 GitHub/GitLab 연결
왕복은 자동 회귀에 포함되어 있지 않으므로, 시연이나 배포 전에 수동으로 한 번 확인한다.

## 5. SMTP 메일 (선택) — 비밀번호 재설정

`spring-boot-starter-mail`의 `JavaMailSender`로 실제 발송한다(`PasswordResetService`).

| 항목 | 값 |
|---|---|
| 환경 변수 | `MAIL_HOST`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_FROM`, `MAIL_SMTP_AUTH`, `MAIL_STARTTLS` |
| 로컬 기본 | `PASSWORD_RESET_CONSOLE_DELIVERY=true` — 메일을 보내지 않고 서버 로그에 링크를 출력한다 |
| 운영 | `PASSWORD_RESET_CONSOLE_DELIVERY=false` + 실제 SMTP 계정 |

> **로컬 Docker에서는 SMTP 발송을 시험할 수 없다.** `compose.yaml`이 `MAIL_*`·
> `PASSWORD_RESET_*`·`PUBLIC_APP_URL`을 전달하지 않으므로 항상 콘솔 출력 기본값으로 동작한다
> (`docker compose logs backend`에서 재설정 링크 확인). 운영은 `env_file`이라 정상 발송된다.
> `ProductionConfigurationValidator`가 `prod` 프로파일에서 `PASSWORD_RESET_CONSOLE_DELIVERY=true`를
> 거부하므로, 운영 배포 전에 SMTP 계정을 반드시 채워야 한다.

## 6. Hugging Face — RAG 로컬 모델 (가입 불필요)

| 항목 | 값 |
|---|---|
| 모델 | `BAAI/bge-m3` (임베딩), `BAAI/bge-reranker-v2-m3` (리랭킹) |
| 환경 변수 | `RAG_LOCAL_EMBED_MODEL`, `RAG_LOCAL_RERANK_MODEL`, `RAG_VECTOR_DIMENSIONS=1024` |
| 인증 | 불필요. `HF_TOKEN` 없이 받으면 속도 제한 경고가 뜨지만 실패가 아니다 |
| 캐시 볼륨 | `jobis-hf-cache` (첫 실행 시 수 GB 다운로드) |

GMS 임베딩으로 바꾸려면 `RAG_EMBED_PROVIDER=gms`, `RAG_RERANK_PROVIDER=gms`, `GMS_KEY`를
설정한다. **provider나 모델을 바꾸면 기존 벡터를 재사용하지 않고 전량 재임베딩한다.**
적재와 검색이 같은 provider·모델·차원을 쓰지 않으면 검색 서버가 기동을 거부한다.

## 7. 인프라 서비스

| 서비스 | 주소 | 용도 |
|---|---|---|
| GitLab | https://lab.ssafy.com/s15-webmobile1-sub1/S15P11C202 | 소스 저장소, MR, protected branch |
| Jenkins | 배포 서버 호스트 | CI/CD (`Jenkinsfile`). 자격증명 `jobis-deploy-ssh`, `jobis-deploy-known-hosts`, GitLab 연결 `ssafy-gitlab` |
| Docker Registry | `JOBIS_IMAGE_PREFIX`로 지정 | Jenkins와 배포 서버가 다른 데몬일 때 필수 (끝에 `/` 포함) |

Jenkins 사전 설정은 [ops/JENKINS_SETUP.md](../ops/JENKINS_SETUP.md)에 있다.
필요 플러그인: Docker Pipeline, SSH Agent, JUnit, GitLab.

## 8. 키 없이 어디까지 되는가

| 구성 | 최소 요구 |
|---|---|
| 로그인·회원가입, 화면 이동 | 외부 키 불필요 |
| 커리어 대화, 공고 분석, 로드맵 | **LLM 키 1개 필수** (1장) |
| 공고 URL 자동 수집 | 대부분 직접 수집으로 동작. JS 렌더 페이지만 폴백 키 필요 |
| 이미지 공고 인식 | CLOVA 키 필요 |
| 저장소 근거 수집 | GitHub App / GitLab OAuth 필요 |
| RAG 공고 추천 | `infra/airflow` 묶음 기동 + 로컬 모델(키 불필요) |
| 비밀번호 재설정 (링크 확인) | 로컬 Docker에서 서버 로그로 확인 가능 |
| 비밀번호 재설정 (메일 발송) | **운영 배포에서만** — 로컬 compose는 `MAIL_*`을 전달하지 않는다 |
| 저장소 근거 수집 | **운영 배포에서만** — 로컬 compose는 `GITHUB_APP_*`·`GITLAB_*`을 전달하지 않는다 |
