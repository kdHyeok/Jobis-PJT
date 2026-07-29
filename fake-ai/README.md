# fake-ai/

개발·시연용 **AI 에이전트 서버**입니다. 환경변수로 기존 Claude Code CLI 또는
로컬 Codex OAuth adapter를 선택하며, 웹 백엔드에 노출하는 HTTP/WebSocket 계약은 같습니다.

한 프로그램에서 두 가지 역할을 흉내냅니다.

| 역할 | 프로토콜 | 설명 |
|---|---|---|
| 실시간 분석 대화 | WebSocket `:8000` | 공고 이해(JOB_CONTEXT) → 진행 → 질문(하나씩) → 로드맵(DONE) 흐름 |
| 커리어 저장소 자료 파편화 | HTTP `POST /extract` | 이력서 등 원문을 파편(fragment)으로 분해 (원샷) |

모델 호출이 실패한 기능은 기존 규칙/고정 응답으로 폴백하거나, 단계형 생성처럼
대체하면 안 되는 기능은 502를 반환합니다.

## 준비물

- Node.js 18+
- Claude 사용 시: 로그인된 `claude` CLI
- Codex 사용 시: `uv`와 로그인된 Codex OAuth adapter

## Provider 선택

`LLM_PROVIDER`를 지정하지 않으면 기존과 동일하게 `claude`를 사용합니다.

| 값 | 실제 호출 |
|---|---|
| `claude` | 기존 `claude -p` 실행 |
| `codex`, `gpt` | 로컬 Codex OAuth adapter의 `POST /v1/chat/completions` |

### Claude — 기존 실행

```powershell
cd C:\Users\SSAFY\work\gitLab\S15P11C202\fake-ai
$env:LLM_PROVIDER = "claude"  # 생략 가능
npm install
node server.js
```

### GPT/Codex — 모델·추론 깊이 유지

Codex adapter는 `uv`가 관리하는 프로젝트 전용 `.venv`에 설치합니다. 최초 설정 시
아래 로그인까지만 수행합니다. 토큰 폐기·인증 파일 손상 등으로 재인증을 요구하면
로그인을 다시 실행합니다.

```powershell
cd C:\Users\SSAFY\work\gitLab\S15P11C202\fake-ai
uv python install 3.11
uv sync --python 3.11 --managed-python --extra server
uv run --managed-python --extra server codex-oauth --login
npm install
```

Codex adapter 소스와 Python 프로젝트 설정은 이 `fake-ai` 디렉터리에 포함되어 있습니다.
외부 `AI` 프로젝트를 실행하거나 참조할 필요가 없습니다. 이후에는 같은 터미널에서
환경변수를 설정하고 실행합니다. `node server.js`가 `8001/health`를 먼저
확인하고, sidecar가 없으면 다음 명령을 자식 프로세스로 자동 실행합니다.

```text
uv run --project <현재 fake-ai 디렉터리> --managed-python --extra server --frozen
  codex-openai-server --host 127.0.0.1 --port 8001
```

```powershell
$env:LLM_PROVIDER = "codex"  # "gpt"도 같은 의미
$env:CODEX_BASE_URL = "http://127.0.0.1:8001"
$env:CODEX_MODEL = "gpt-5.4"
$env:CODEX_REASONING_EFFORT = "medium"
$env:CODEX_TIMEOUT_MS = "200000"
node server.js
```

정상 자동 기동 로그:

```text
[LLM] provider=codex
[LLM:codex] uv sidecar 시작: 127.0.0.1:8001
[LLM:codex] sidecar 준비 완료: http://127.0.0.1:8001
```

기본 adapter 위치는 `server.js`와 같은 `fake-ai` 디렉터리입니다.
`CODEX_ADAPTER_PATH`는 별도 adapter를 시험할 때만 선택적으로 지정합니다. 이미 실행 중인
sidecar가 있으면 새로 띄우지 않고 재사용합니다. 자동 기동을 원하지 않으면
`CODEX_AUTO_START=0`을 설정합니다.

`CODEX_REASONING_EFFORT`는 `minimal`, `low`, `medium`, `high`, `xhigh`, `max`,
`ultra`를 받을 수 있습니다. 실제 지원 모델과 추론 단계는 로그인한 계정과 모델에 따라
달라집니다. `minimal`은 참조 adapter가 Codex backend에 `low`로 전달합니다.

Codex sidecar 기본 구성은 단일 worker이므로 `codex`/`gpt` 선택 시 동시 모델 호출은
기본 1개로 직렬화됩니다. 여러 worker를 별도로 구성한 경우에만
`LLM_MAX_CONCURRENT`를 그 수에 맞춰 명시적으로 조정하세요. Claude 기본값은 기존과
동일하게 2개입니다.

Codex adapter 프로세스와 실제 인증·모델 접근을 차례로 확인하려면:

```powershell
Invoke-RestMethod http://127.0.0.1:8001/health
Invoke-RestMethod http://127.0.0.1:8001/v1/models
```

이 서버는 `.env`를 자동으로 읽지 않습니다. 위 환경변수는 `node server.js`를 실행하는
동일한 터미널에 설정해야 합니다.

위 Codex 절차는 로컬 개발 기준입니다. 운영 systemd에서 자동 기동하려면 서비스 사용자가
`uv`와 배포된 `fake-ai` 디렉터리에 접근할 수 있어야 하며, 동일한
`LLM_PROVIDER`·`CODEX_*` 환경변수를 `jobis-fake-ai.service`에 주입해야 합니다.
sidecar는 API key가 없으므로 loopback 밖으로 공개하지 않습니다.

## 공통 실행 결과

→ `ws://localhost:8000` 대기. **이 서버가 떠 있어야 백엔드의 분석 기능이 동작한다.** 백엔드보다 먼저 실행할 것.

테스트:

```powershell
npm test
```

## 백엔드와의 관계

웹 백엔드는 원문만 전달하고, 분석·파싱은 전부 이 서버가 담당합니다. 백엔드 실행 방법은 [backend/README.md](../backend/README.md) 참고.
