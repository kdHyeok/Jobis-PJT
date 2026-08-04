# JOBISS AI/v2bridge

Spring 백엔드의 `/v1/*` HTTP 계약을 구현하는 JOBISS 정본 AI 서버다. 내부는 LangGraph
오케스트레이터, 역할별 에이전트, 결정론 판단 도구, 선택 가능한 LLM/RAG adapter로 구성된다.

코딩 규약은 `AGENTS.md`, 결정 이력은 `docs/decisions.md`, 현재 구조는
`docs/agent-structure-current.md`가 정본이다.

## 요청 경로

```text
Spring backend
  -> FastAPI v2bridge
  -> v2bridge service/mapping
  -> orchestrator + agents + graph
  -> LLM provider / optional RAG
```

주요 엔드포인트:

- `GET /health`
- `POST /v1/analyses`, `/v1/analyses/stream`
- `POST /v1/chat`, `/v1/chat/stream`
- `POST /v1/career-extractions`
- `POST /v1/evidence-verifications`
- `POST /v1/competency-assessments`

인증 헤더는 `X-JOBISS-AI-SECRET`이며 `JOBISS_AI_SHARED_SECRET` 또는 공용 운영 env의
`AI_SHARED_SECRET`과 비교한다. 서비스 DB 자격증명은 받지 않는다.

## 로컬 실행

```powershell
cd AI
Copy-Item .env.example .env
# .env에서 사용할 provider와 인증만 설정
uv run --frozen --extra prototype python -m uvicorn `
  jobis_ai.v2bridge.app:app --host 127.0.0.1 --port 8000
```

```powershell
curl.exe -fsS http://127.0.0.1:8000/health
```

응답의 `service`는 `jobis-ai-v2bridge`여야 한다.

## LLM provider

모든 provider는 같은 LangChain `.invoke()` 경계와 같은 에이전트 지침을 사용한다.

| `LLM_PROVIDER` | 인증 | 주요 설정 |
|---|---|---|
| `openai` | `GMS_KEY` | `LLM_BASE_URL`, `LLM_MODEL*` |
| `anthropic` | `ANTHROPIC_API_KEY` | `ANTHROPIC_MODEL` |
| `claude_code` | 로그인된 Claude Code CLI | `CLAUDE_CODE_MODEL*` |
| `codex`/`gpt` | Codex OAuth | `CODEX_MODEL*`, `CODEX_REASONING_EFFORT` |

Codex 최초 로그인:

```powershell
uv run jobis-codex-oauth --login
```

운영에서는 `CODEX_OAUTH_STATE_DIR=/var/lib/jobis-ai/codex`처럼 영속 볼륨 경로를
명시한다. `auth.json`의 내용은 출력·로그·커밋하지 않는다. 외부 구현 출처는 `NOTICE`에 있다.

## RAG

- `RAG_PROVIDER=http`: `RAG_SEARCH_URL/search` 호출
- `RAG_PROVIDER=local_postings`: `POSTINGS_DB_DIR`의 공고 JSON 검색
- `null`: 데이터가 있으면 local postings, 없으면 미연결

HTTP RAG 실패는 로컬 공고 검색으로 폴백하고 `rag_http_failed` 경고를 남긴다. 운영 Airflow
RAG 서버의 기본 주소는 `http://127.0.0.1:8765`다.

## 영속 상태

서비스 DB의 진실 원장은 Spring/PostgreSQL이다. AI가 유지하는 별도 운영 상태는 다음과 같다.

- `SESSION_DB_PATH`: 대화 자산 SQLite
- `CODEX_OAUTH_STATE_DIR`: Codex OAuth 상태
- `JOBIS_AUDIT_LOG`: 정책 결정 감사 JSONL
- `JOBIS_TRACE_DIR`: 선택적 턴 trace

Docker에서는 모두 `/var/lib/jobis-ai` 볼륨 아래에 둔다.

## 검증

```bash
uv run --frozen --extra dev --extra prototype pytest -q
uv run --frozen --extra prototype python -m jobis_ai.explain
```

실 LLM 평가 하네스는 비용과 외부 상태를 사용하므로 큰 provider/프롬프트 변경에서만 별도로
실행하고, 단위 테스트 통과를 실제 provider 성공으로 표현하지 않는다.

전체 Docker/CI/CD/백업/롤백은 저장소 루트 `ops/DEPLOYMENT.md`를 따른다.
