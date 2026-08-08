# 웹 브릿지 — 웹의 UI·DB를 그대로 두고 뇌만 갈아끼우기

웹(Spring 백엔드 + `backend/src/main/resources/static`)은 지금까지 `fake-ai`(node, `:8000`)와
대화했다. 이 브릿지는 **그 자리에 그대로 들어가는 FastAPI 서버**다. 웹의 화면·DB 스키마·백엔드
코드는 한 줄도 바꾸지 않는다.

```
chat.html ─STOMP─ Spring(FakeAgentClient) ─WS :8000─ webbridge ─→ 오케스트레이터 · 판정 그래프(LangGraph)
                                          ─HTTP :8000─
```

## 실행

```bash
# 의존성 (한 번)
uv sync --extra prototype

# 브릿지 (fake-ai 대신 이걸 켠다)
uv run uvicorn jobis_ai.webbridge.app:app --host 127.0.0.1 --port 8000
```

포트 8000 · 루트 경로를 지키는 이유는 백엔드 설정(`application.yml` 의 `jobiss.agent.url`,
`jobiss.agent.http-url`)을 건드리지 않기 위해서다. 즉 **fake-ai 를 끄고 이걸 켜면 끝**이다.

### 8000 이 이미 쓰이고 있을 때

관찰 UI(`jobis_ai.prototype.app`)도 기본이 8000이고, 팀원이 그걸 쓰고 있을 수 있다.
**남의 프로세스를 죽이지 말고** 브릿지를 다른 포트로 띄운다. `application.yml` 이 이미
환경변수를 읽게 되어 있어서(`${AGENT_WS_URL:...}`) 코드도 설정 파일도 고칠 필요가 없다:

```bash
# AI 쪽
uv run uvicorn jobis_ai.webbridge.app:app --port 8100

# 백엔드 쪽 (실행 환경에만 지정)
AGENT_WS_URL=ws://localhost:8100 AGENT_HTTP_URL=http://localhost:8100 ./gradlew bootRun
```

지금 8000 을 누가 쓰는지 확인:

```bash
netstat -ano | findstr :8000        # 윈도우
```

`.env` 에 `GMS_KEY` 가 없으면 판정 노드가 폴백으로 돌아 결과가 비거나 샘플이 된다 — 실제 대화를
돌릴 때는 키를 먼저 확인한다.

### DB 없이 바로 대화 (브릿지 개발용)

백엔드·브라우저·DB 없이 브릿지만 띄워 놓고 대화를 돌릴 수 있다. 웹백엔드와 **같은 WS 계약**으로
말하는 클라이언트라, 여기서 보이는 게 브라우저에 중계되는 것과 같다.

```bash
uv run python scripts/webbridge_chat.py --url ws://127.0.0.1:8100/

# 내 공고·자료로
uv run python scripts/webbridge_chat.py --posting 공고.txt --evidence 자료.txt --json
```

**브릿지는 웹 DB를 건드리지 않는다.** 판정 결과를 저장하는 것은 백엔드이고, 브릿지가 지키는 것은
`DONE.result` 의 JSON 형태뿐이다. 그래서 DB 엔진 교체(MySQL → PostgreSQL)는 브릿지와 무관하다 —
백엔드의 `datasource`·마이그레이션만 바뀐다.

### 세션 저장소

대화 맥락(세션 자산: 이력서·공고·분석·로드맵·대화 이력)은 **AI 쪽 SQLite 파일**에 영속한다
(`AI/sessions.sqlite3`, `orchestrator/session.py`). 프로세스를 재시작해도 남으므로,
분석을 끝낸 뒤 "자소서 써줘"로 이어가는 흐름이 서버 재시작에 끊기지 않는다.

```bash
SESSION_STORE=sqlite            # 기본. memory 로 두면 프로세스 안에만 (테스트·일회성)
SESSION_DB_PATH=/path/sessions.sqlite3   # 기본은 AI/sessions.sqlite3
```

웹 DB(MySQL/PostgreSQL)에 붙이지 않은 이유는 이 패키지가 웹 인프라에 의존하지 않게 하려는 것이다.
저장 위치를 옮겨야 하면 `session.py` 의 구현(get/update/clear 세 메서드)만 갈아끼운다.

주의: `get()` 은 **복사본**을 준다. 받은 dict 를 고쳐도 저장되지 않으니 저장은 `update()` 로 한다.

## 지키는 계약

계약의 출처는 세 곳이고, 바꾸면 UI 가 조용히 깨진다. `protocol.py` 에 모아 뒀다.

| 출처 | 무엇을 정하는가 |
|---|---|
| `fake-ai/server.js` | WS 메시지 형태(`send`/`sendAgentProgress`), HTTP 4개 라우트 |
| `FakeAgentClient.handle()` | `JOB_CONTEXT`·`DONE` 에서 DB에 저장하는 키 |
| `static/chat.html` | `AGENT_META`/`AGENT_STAGE`, `onProgress`/`onQuestion`/`onDone` 이 읽는 필드 |

### WS (`ws://localhost:8000`)

받는 것: `START`(공고 원문 + 저장소 자료), `USER_MESSAGE`(질문에 대한 답)
보내는 것: `JOB_CONTEXT` · `PROGRESS` · `QUESTION` · `AGENT_MESSAGE` · `DONE` · `ERROR`

`PROGRESS.agent` 는 **판정 그래프의 노드 이름을 그대로** 쓴다. `chat.html` 의 에이전트 레일 키가
이미 노드명과 같아서(`parse_job_posting` … `assemble_output`) 매핑이 필요 없다.

### HTTP

| 라우트 | 호출부 | 하는 일 |
|---|---|---|
| `POST /extract` | `EvidenceImportService` | 이력서 원문 → 저장소 조각. `build_user_profile` 을 그대로 부른다 |
| `POST /roadmap` | `SavedRoadmapService` | 선택 경로의 준비 로드맵 (직전 분석 근거 재사용) |
| `POST /reassess` | `SavedRoadmapService` | 제출 링크가 스텝 요건을 증명하는지 (규칙 판정) |
| `POST /roadmap-ask` | `SavedRoadmapService` | 로드맵 Q&A |

## 파일

| 파일 | 역할 |
|---|---|
| `app.py` | FastAPI 라우팅. WS 수신 루프 + HTTP 4개 |
| `protocol.py` | 웹 WS 계약(메시지 형태·에이전트 카탈로그) |
| `runner.py` | 그래프 실행(워커 스레드) · 진행 스트리밍 · 질문 왕복 |
| `adapter.py` | 판정 결과 → 웹 리포트(`DONE.result`) |
| `http_handlers.py` | HTTP 4개 라우트의 실제 처리 |
| `store.py` | 직전 분석 보관(단발 HTTP 요청이 근거를 재사용하도록) |

## 설계 판단 세 가지

**1. 질문 왕복은 "다시 돌린다"로 구현했다.**
웹 계약은 한 WS 세션 안에서 `QUESTION` → 답 → 이어서 분석을 요구한다. 그런데 판정 그래프에는
재개 경로가 없다(`ask_user` → `assemble_output` 으로 끝나고 `status=need_more_info`). 그래서
브릿지가 답변을 **이력서 원문에 면담 기록으로 덧붙여 파이프라인을 다시 돌린다**. 답이 근거로 남아
`build_user_profile` 이 추출하고 `gap_matcher` 가 인용하므로, 답변이 판정에 실제로 반영된다.
라운드는 `MAX_QUESTION_ROUNDS` 로 제한한다(답해도 여전히 부족할 수 있어 무한 왕복 방지).

**2. 웹에만 있는 개념은 규칙으로 파생시켰다.**
`decision`(목표 상태 판정)과 `routes`(지원 경로 카드)는 판정 엔진에 없는 웹 전용 개념이다.
LLM 을 새로 부르지 않고, 확정된 요건 판정·점수만으로 규칙으로 만든다(`adapter.py`).
`경력 N년`·`학위` 같은 **구조적 제약**은 따로 식별해서 로드맵 상승폭(`delta`)에서 빼고
"준비 과제로 보완"이라고 쓰지 않는다 — 로드맵을 다 해도 채워지지 않는 조건이다.

**3. 근거가 없으면 만들지 않는다.**
- `/extract` 는 LLM 미설정이면 **빈 목록**을 준다. 샘플 프로필을 저장소에 넣으면 그 뒤 모든
  판정이 남의 이력 위에서 돌아간다.
- 대체 공고는 출처 공고(`rawText`)가 있는 것만 카드로 낸다. 빈 원문으로 "이 공고로 재분석"이
  눌리면 빈 공고를 분석하게 된다. 출처 없는 제안은 `result.trace.alternativeSuggestions` 에 남는다.
- RAG 가 연결되지 않은 동안은 대체 공고 카드가 비는 것이 정상이다(`trace.warnings` 에
  `rag_not_connected` 로 남는다).

## 남은 것

- **`store.py` 의 키가 (회사, 직무)다.** 웹이 `/roadmap` 에 분석 식별자를 보내지 않아서
  직전 분석을 추정해 쓴다. 백엔드가 `analysisId` 를 함께 보내면 정확해진다(웹 변경 필요).
- **`/reassess` 는 규칙 판정이다.** 링크를 열어 내용으로 판정하지 않는다. 지금 단정하면
  "확인했다"가 근거 없이 나간다.
- **Spring 백엔드 + 브라우저까지 이어 붙인 검증은 아직이다.** 브릿지 단독(START→DONE)과
  HTTP 4개는 실제 LLM 으로 확인했다.
