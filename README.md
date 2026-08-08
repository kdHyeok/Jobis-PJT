# JOBIS 단일 AI 통합 작업공간

`C:\JOBIS`는 최신 팀 에이전트와 회사 맞춤 프로젝트·원자 역량·Capability Graph·커리어
그래프 기능을 하나의 JOBIS AI 서버로 통합하는 독립 작업공간입니다.

비교 원본인 `C:\S15P11C202`와 `C:\jobiss-service-v3-integration-lab`은 수정하지 않습니다.
이 폴더는 Git 작업공간이 아니며, 명시적인 요청 없이 커밋·Push·데이터 초기화를 하지 않습니다.

## 현재 구조

```text
Vue :5473
  → Spring Boot :8380
      → PostgreSQL :58432
      → JOBIS AI :8400
          ├─ 자유 대화와 역할별 에이전트
          ├─ 공고 수집·복수 직무 확인
          ├─ 적합도·회사 맞춤 프로젝트 설계
          ├─ 원자 역량 정규화
          └─ 사용자 커리어 그래프 제안
              → Capability Graph :8600 (읽기 전용 지식 데이터)
```

Spring과 PostgreSQL이 사용자 대화, 질문·답변, 분석 상태, 취소, 로드맵 초안과 버전의 정본입니다.
공고 분석은 결과를 즉시 지도에 덮어쓰지 않고 `DRAFT → 미리보기 → 적용 또는 취소`를 거칩니다.

## 처음 설치

Java 17, Python 3.12, Node.js와 Codex CLI 로그인이 필요합니다.

```powershell
cd C:\JOBIS
powershell -ExecutionPolicy Bypass -File .\scripts\start-all.ps1 -Install
```

## 실행

한 줄로 모두 실행:

```powershell
powershell -ExecutionPolicy Bypass -File C:\JOBIS\scripts\start-all.ps1
```

로그가 보이는 별도 창으로 실행하려면 `JOBIS-START.cmd`를 실행합니다. 개별 실행 파일도 있습니다.

- `JOBIS-START-CAPABILITY-GRAPH.cmd`: 공용 원자 역량 그래프
- `JOBIS-START-AI.cmd`: 단일 JOBIS AI
- `JOBIS-START-BACKEND.cmd`: PostgreSQL 준비 후 Spring Boot
- `JOBIS-START-FRONTEND.cmd`: Vue/Vite
- `JOBIS-STOP.cmd`: 이 작업공간의 서비스와 PostgreSQL 종료
- `JOBIS-RESET-DATA.cmd`: 서버를 시작하지 않고 이 작업공간 DB만 초기화

웹앱: [http://localhost:5473](http://localhost:5473)

| 구성 | 주소 |
|---|---|
| PostgreSQL | `localhost:58432/jobiss_v3_integration_lab` |
| JOBIS AI | `http://127.0.0.1:8400` |
| Capability Graph | `http://127.0.0.1:8600` |
| Spring Boot | `http://localhost:8380` |
| Vue/Vite | `http://localhost:5473` |

## AI 설정

`scripts\start-ai-agent.ps1`은 이 작업공간의 AI 호출을 Codex CLI로 고정합니다. 설정 파일 탐색
순서는 `AI\.env`, 루트 `.env`, `C:\Users\SSAFY\Downloads\env`입니다. 다른 파일을 쓰려면:

```powershell
powershell -ExecutionPolicy Bypass -File C:\JOBIS\scripts\start-ai-agent.ps1 `
  -EnvFile C:\path\to\env
```

로컬 실행에서는 `CAPABILITY_GRAPH_URL`이 비어 있으면 `http://127.0.0.1:8600`으로 자동 설정하고,
`start-capability-graph.ps1`과 동일한 로컬 공유 비밀값을 사용합니다. 이 환경변수는 AI 프로세스가
시작될 때 한 번 읽히므로 설정을 바꾼 뒤에는 AI 서버를 재시작해야 합니다.

공고 URL·본문·이미지는 같은 source 계약으로 들어갑니다. 여러 직무나 혼합 경력이 있으면 임의로
합치지 않고 사용자 확인을 기다립니다. 확인 뒤 회사 맞춤 프로젝트를 먼저 설계하고, 필요한 원자
역량과 선수관계를 Capability Graph에서 조회해 하나의 사용자 커리어 그래프 초안을 만듭니다.

## IntelliJ에서 백엔드 실행

Project SDK와 Gradle JVM을 Java 17로 설정한 뒤 `JobissBackendApplication`을 실행합니다.
명령줄에서는:

```powershell
cd C:\JOBIS\backend
$env:JAVA_HOME="C:\Program Files\Eclipse Adoptium\jdk-17.0.19.10-hotspot"
$env:Path="$env:JAVA_HOME\bin;$env:Path"
.\gradlew.bat bootRun
```

백엔드만 실행할 때는 먼저 `scripts\start-local-postgres.ps1`로 DB를 준비합니다.

## 검증

```powershell
powershell -ExecutionPolicy Bypass -File C:\JOBIS\scripts\check.ps1
```

검사 범위는 Spring, 단일 JOBIS AI(내부 career pipeline 포함), Capability Graph, 프론트
단위 테스트·빌드·E2E와 격리 PostgreSQL 검증입니다. 환경 부족으로 건너뛴 검사는 성공으로
간주하지 않습니다.

## 중요 문서

- `AGENTS.md`: 작업 규칙과 격리 범위
- `TASK.md`: 현재 구현 상태와 정확한 다음 행동
- `docs\07-decision-register.md`: 확정 결정
- `docs\23-d047-latest-baseline-audit.md`: 최신 AI와 기존 통합판 비교
- `docs\24-d047-single-ai-file-plan.md`: 단일 AI 파일 단위 구현 설계
- `docs\05-regression-scenarios.md`: 반드시 막아야 할 회귀 사례
