# JOBISS Docker 재현 실행 가이드

이 문서는 `feat/infra/airflow` 브랜치를 새로 받은 사람이 Windows PowerShell에서 다음 두
Docker Compose 묶음을 같은 방식으로 실행하고 검증하기 위한 런북이다.

| Compose 묶음 | 파일 | 역할 | 외부 포트 |
|---|---|---|---|
| `jobis-app` | 저장소 루트 `compose.yaml` | Frontend + Backend + AI + 서비스 PostgreSQL | `8088` |
| `jobis-data-pipeline` | `infra/airflow/docker-compose.yml` | Airflow + 수집/OCR + RAG 적재/검색 + pgvector | `8081`, `8765` |

두 묶음은 목적과 DB 계약이 다르므로 환경 파일도 따로 사용한다.

- 서비스 묶음: 저장소 루트 `.env`
- 데이터 파이프라인: `infra/airflow/.env`

`.env` 파일, API 키, 비밀번호, JWT, OAuth 상태 파일은 Git에 올리지 않는다.

## 1. 준비 환경

### 필수

- Windows 10/11 + PowerShell 5.1 이상
- Git
- Docker Desktop 최신 안정 버전
  - WSL 2 기반 Linux containers 사용
  - Docker Compose v2 사용 (`docker compose`, 하이픈 없음)
- 첫 이미지 빌드와 모델 다운로드를 위한 인터넷 연결
- Codex provider를 사용할 경우 브라우저와 Codex 사용 권한이 있는 OpenAI 계정

확인 명령:

```powershell
git --version
docker version
docker compose version
docker info --format '{{.OSType}}'
```

마지막 명령은 `linux`를 출력해야 한다. Docker Desktop이 실행되지 않았거나 Windows
containers 모드이면 먼저 Linux containers로 전환한다.

### 권장 자원

- CPU: 4코어 이상
- 메모리: Docker Desktop에 10~12GB 이상 할당
- 디스크 여유: 20GB 이상

로컬 BGE-M3 적재와 리랭킹은 기본적으로 컨테이너당 최대 2 CPU를 사용한다. Docker의 CPU
표시는 코어 하나가 100%이므로 `docker stats`에서 약 200%가 보이면 2코어 제한 안에서 정상이다.

### 선택: 소스 전체 검증 환경

Docker 실행만 할 때는 필요하지 않다. `scripts/check.ps1`까지 실행하려면 다음도 설치한다.

- Java 17 이상
- Node.js/npm
- Python 패키지 실행기 `uv`

## 2. 브랜치 준비

이미 저장소가 있다면 다음처럼 정확한 브랜치로 이동한다.

```powershell
cd C:\Users\<사용자>\work\data-airflow
git fetch origin
git switch feat/infra/airflow
git pull --ff-only
git status --short --branch
```

다른 경로에 clone해도 되지만, 이후 명령은 반드시 저장소 루트 또는 명시된 하위 디렉터리에서
실행한다.

## 3. PowerShell 5.1 호환 비밀값 생성

다음 값은 “암호화된 문자열”이라기보다 암호학적으로 안전한 난수다. 각 변수마다 다른 값을
생성하고 비밀번호 관리자에 보관한다. URL이나 PostgreSQL DSN에 넣기 쉬운 64자리 16진수라서
특수문자 이스케이프 문제도 피할 수 있다.

PowerShell 5.1에는 `RandomNumberGenerator.Fill()`과 `Convert.ToHexString()`이 없으므로
다음 함수를 사용한다.

```powershell
function New-SafeSecret {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    }
    finally {
        $rng.Dispose()
    }

    [System.BitConverter]::ToString($bytes).Replace('-', '').ToLowerInvariant()
}

function New-FernetKey {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    }
    finally {
        $rng.Dispose()
    }

    [System.Convert]::ToBase64String($bytes).Replace('+', '-').Replace('/', '_')
}

New-SafeSecret
New-FernetKey
```

- `New-SafeSecret`: DB 비밀번호, `JWT_SECRET`, `AI_SHARED_SECRET` 등에 사용
- `New-FernetKey`: `AIRFLOW_FERNET_KEY`에만 사용
- 출력된 실제 값은 채팅, 이슈, MR, 로그에 붙이지 않는다.

## 4. 서비스 환경 파일 준비

저장소 루트에서 예제 파일을 복사한다.

```powershell
cd C:\Users\<사용자>\work\data-airflow
Copy-Item .env.compose-local.example .env
```

루트 `.env`에서 최소한 다음 항목을 확인하거나 교체한다.

| 변수 | 설정 방법 |
|---|---|
| `POSTGRES_MIGRATOR_PASSWORD` | `New-SafeSecret`의 새 출력 |
| `POSTGRES_APP_PASSWORD` | 위와 다른 새 출력 |
| `JWT_SECRET` | 위와 다른 새 출력, 최소 32바이트 |
| `AI_SHARED_SECRET` | 위와 다른 새 출력. Backend와 AI에 같은 값이 주입됨 |
| `LLM_PROVIDER` | Codex 로그인은 `codex`, GMS는 `openai`, Anthropic은 `anthropic` |
| `RAG_PROVIDER` | RAG 서버를 연결하면 `http`, 아직 실행하지 않으면 `null` |
| `RAG_SEARCH_URL` | Docker 실행에서는 `http://host.docker.internal:8765` |
| `ALLOWED_ORIGINS` | 로컬 기본값 `http://localhost:8088` |
| `COOKIE_SECURE` | HTTP 로컬 실행은 `false` |
| `SPRING_PROFILES_ACTIVE` | 로컬 실행은 `local` |

Codex를 사용할 때의 핵심 설정:

```dotenv
LLM_PROVIDER=codex
CODEX_MODEL=gpt-5.4
CODEX_MODEL_LIGHT=gpt-5.4
CODEX_REASONING_EFFORT=medium
RAG_PROVIDER=http
RAG_SEARCH_URL=http://host.docker.internal:8765
```

선택하지 않은 provider의 키는 비워 둬도 된다. 예를 들어 Codex를 사용하면
`ANTHROPIC_API_KEY`와 `GMS_KEY`는 비어 있어도 된다.

## 5. Airflow/RAG 환경 파일 준비

Airflow Compose 디렉터리에서 별도의 환경 파일을 만든다.

```powershell
cd C:\Users\<사용자>\work\data-airflow\infra\airflow
Copy-Item .env.example .env
```

다음 값은 각각 새로 생성한다.

| 변수 | 설정 방법 |
|---|---|
| `POSTGRES_PASSWORD` | `New-SafeSecret` |
| `AIRFLOW_DB_PASSWORD` | 별도의 `New-SafeSecret` |
| `JOBRAG_DB_PASSWORD` | 별도의 `New-SafeSecret` |
| `AIRFLOW_ADMIN_PASSWORD` | 별도의 강한 비밀번호 |
| `AIRFLOW_FERNET_KEY` | `New-FernetKey` |
| `JOBRAG_DB_NAME` | 기본값 `jobrag` 유지 |
| `DOCKER_GID` | Windows Docker Desktop은 우선 기본값 `999` 사용 |

처음 재현할 때는 비용이 발생하지 않는 로컬 모델 설정을 권장한다.

```dotenv
RAG_EMBED_PROVIDER=local
RAG_RERANK_PROVIDER=local
RAG_LOCAL_EMBED_MODEL=BAAI/bge-m3
RAG_LOCAL_RERANK_MODEL=BAAI/bge-reranker-v2-m3
RAG_VECTOR_DIMENSIONS=1024

RAG_LOCAL_CPU_THREADS=2
RAG_INGEST_CPUS=2.0
RAG_SEARCH_CPUS=2.0
RAG_EMBED_BATCH_SIZE=8
RAG_INGEST_WINDOW_SIZE=64
RAG_LOCAL_RERANK_BATCH_SIZE=4

GMS_KEY=
```

저장소에 포함된 기본 SQLite를 사용하려면 `JOBIS_LEGACY_SQLITE_PATH`는 예제 값을 그대로
둔다. 다른 파일을 사용한다면 Windows 절대 경로를 `/`로 작성한다.

```dotenv
JOBIS_LEGACY_SQLITE_PATH=C:/Users/<사용자>/Downloads/all_job_postings.db
```

Docker Desktop에서 해당 드라이브의 파일 공유가 허용되어 있어야 한다.

### GMS RAG로 변경할 때

```dotenv
RAG_EMBED_PROVIDER=gms
RAG_RERANK_PROVIDER=gms
GMS_KEY=<발급받은 값>
```

provider나 모델을 바꾸면 기존 벡터를 재사용하지 않고 전량 재임베딩한다. 수천 개 청크를 한 번에
GMS로 적재하면 키 한도나 과금량을 빠르게 소진할 수 있으므로, 최초 재현은 로컬 provider로 한다.

## 6. Airflow/RAG 이미지 빌드와 실행

`rag-search`는 Compose 서비스지만, Airflow의 DockerOperator가 실행하는 `rag-ingest`는
별도 이미지다. 둘 다 빌드해야 한다.

```powershell
cd C:\Users\<사용자>\work\data-airflow\infra\airflow

docker compose config --quiet
docker compose build

docker build `
    -t jobis/rag-ingest:latest `
    -f Dockerfile.rag-ingest `
    ..\..

docker compose up -d
docker compose ps -a
```

첫 실행에는 다음 작업 때문에 시간이 걸린다.

- Airflow/pgvector 이미지 빌드
- Hugging Face BGE-M3 및 reranker 모델 다운로드
- PostgreSQL 초기화
- Flyway `jobrag` 스키마 마이그레이션
- Airflow 메타 DB와 관리자 계정 생성

정상 상태:

- `postgres`: `healthy`
- `rag-search`: 모델 warmup 후 `healthy`
- `airflow-scheduler`, `airflow-webserver`: `running`
- `jobrag-migrate`, `airflow-init`: `Exited (0)`

`jobrag-migrate`와 `airflow-init`은 한 번 실행하고 종료되는 작업이므로 `Exited (0)`이 성공이다.
실패했다면 다음 로그부터 확인한다.

```powershell
docker compose logs --tail 200 postgres jobrag-migrate airflow-init
docker compose logs --tail 200 rag-search airflow-scheduler airflow-webserver
```

## 7. Airflow DAG 준비와 최초 데이터 적재

먼저 DAG import 오류가 없어야 한다.

```powershell
cd C:\Users\<사용자>\work\data-airflow\infra\airflow
docker compose exec airflow-scheduler airflow dags list-import-errors
```

`No data found`가 나오면 import 오류가 없다는 의미다. 최초 실행에서는 운영 DAG 네 개를
unpause한다.

```powershell
docker compose exec airflow-scheduler airflow dags unpause jobis_collect
docker compose exec airflow-scheduler airflow dags unpause jobis_load_postgres
docker compose exec airflow-scheduler airflow dags unpause jobis_ocr
docker compose exec airflow-scheduler airflow dags unpause jobis_rag
```

출력의 `is_paused=False`가 정상이다. 같은 명령을 다시 실행해도 문제없다.

### 저장소에 포함된 SQLite를 최초 1회 import

```powershell
docker compose exec airflow-scheduler airflow dags unpause jobis_legacy_import
docker compose exec airflow-scheduler airflow dags trigger jobis_legacy_import
```

Trigger 결과의 `state=queued`는 실행 요청이 접수되었다는 뜻일 뿐 성공을 의미하지 않는다.
Airflow UI에서 `validate_sqlite → prepare_import → import_postgres → verify_import`가 모두
성공했는지 확인한다.

- Airflow UI: `http://localhost:8081`
- 사용자: `admin`
- 비밀번호: `infra/airflow/.env`의 `AIRFLOW_ADMIN_PASSWORD`

CLI로도 실행 상태를 확인할 수 있다.

```powershell
docker compose exec airflow-scheduler `
    airflow dags list-runs -d jobis_legacy_import --no-backfill

docker compose exec airflow-scheduler `
    airflow dags list-runs -d jobis_rag --no-backfill
```

레거시 import가 성공하면 Dataset 이벤트가 `jobis_rag`를 자동으로 연결한다. 필요하면 RAG만
직접 실행할 수 있다.

```powershell
docker compose exec airflow-scheduler airflow dags trigger jobis_rag
```

일회성 import가 끝나면 실수로 다시 실행하지 않도록 pause한다.

```powershell
docker compose exec airflow-scheduler airflow dags pause jobis_legacy_import
```

### RAG 적재 컨테이너 로그 확인

Airflow DockerOperator가 만드는 적재 컨테이너는 `laughing_ritchie` 같은 임의 이름을 가질 수
있다. 이 컨테이너는 Compose 서비스가 아니며 작업 종료 후 제거될 수 있으므로 화면에 보인 이름을
오래 저장해 두지 않는다.

```powershell
$ragContainer = docker ps `
    --filter "ancestor=jobis/rag-ingest:latest" `
    --format "{{.ID}}" |
    Select-Object -First 1

if ($ragContainer) {
    docker logs -f $ragContainer
}
else {
    Write-Host "현재 실행 중인 rag-ingest 컨테이너가 없습니다. Airflow DAG 상태를 확인하세요."
}
```

적재 로그의 다음 부분을 확인한다.

```text
[load] ...
[chunk] ...
[embed] 신규/변경 ...
[store_postings] ...
[store_chunks] ...
```

`[store_postings]`, `[store_chunks]`까지 출력되고 DAG run이 `success`여야 완료다. 적재는 새
임베딩을 모두 계산한 뒤 원자적으로 반영하므로 실행 중인 일부 청크는 검색에 노출되지 않는다.
기존에 성공한 인덱스가 있으면 새 적재 중에도 그 인덱스로 검색할 수 있다.

다음 경고는 그 자체로 실패가 아니다.

- `RemovedInAirflow3Warning`: Airflow 3 전환 경고
- `unauthenticated requests to the HF Hub`: `HF_TOKEN` 없이 모델을 받는다는 속도 제한 경고
- 일회성 `docker compose run --rm ...` 컨테이너의 임의 이름

## 8. Codex OAuth 로그인

루트 `.env`에서 `LLM_PROVIDER=codex`로 설정한 뒤 AI 이미지를 먼저 빌드한다.

```powershell
cd C:\Users\<사용자>\work\data-airflow
docker compose build ai
```

Docker 이미지에서는 프로젝트 console script가 설치되지 않으므로 다음 명령은 사용하지 않는다.

```text
docker compose run --rm --entrypoint jobis-codex-oauth ai --login
```

위 명령은 `executable file not found in $PATH`로 실패할 수 있다. 현재 이미지에서 검증된 진입점은
Python 모듈 실행이다.

```powershell
docker compose run --rm --no-deps `
    --entrypoint python `
    ai -m jobis_ai.codex_oauth_adapter.cli --login
```

터미널에 다음 정보가 표시된다.

1. `https://auth.openai.com/codex/device` 주소
2. 일회용 인증 코드
3. 로그인 완료 대기 메시지

브라우저에서 주소를 열고 코드를 입력한다. 로그인 완료 후 인증 상태는 AI 영속 볼륨의
`/var/lib/jobis-ai/codex/auth.json`에 저장된다. 파일 내용은 열거나 출력하거나 Git에 올리지
않는다.

토큰/API 접근 확인:

```powershell
docker compose run --rm --no-deps `
    --entrypoint python `
    ai -m jobis_ai.codex_oauth_adapter.cli --models
```

모델 목록이 출력되면 로그인 상태를 실제 API로 확인한 것이다. `/health` 성공만으로는 Codex
실호출까지 증명되지 않는다.

## 9. 전체 애플리케이션 실행

RAG 검색을 연결한다면 먼저 `http://localhost:8765/health`가 준비된 뒤 루트 서비스를 올린다.

```powershell
cd C:\Users\<사용자>\work\data-airflow

docker compose config --quiet
docker compose up --build -d
docker compose ps
```

정상 상태:

- `postgres`, `ai`, `backend`: `healthy`
- `frontend`: `running`

접속 주소:

- JOBISS 웹: `http://localhost:8088`
- Backend health 프록시: `http://localhost:8088/api/health`
- Airflow: `http://localhost:8081`
- RAG health/search: `http://localhost:8765/health`, `POST /search`

PostgreSQL과 AI 8000 포트는 루트 Compose 내부 네트워크에만 열려 있다. 호스트에서 AI
`localhost:8000`에 접속되지 않는 것이 현재 Docker 구성에서는 정상이다.

## 10. 상태 확인

### 전체 Compose 상태

```powershell
cd C:\Users\<사용자>\work\data-airflow
docker compose ps -a
docker compose logs --tail 100 ai backend frontend

cd infra\airflow
docker compose ps -a
docker compose logs --tail 100 rag-search airflow-scheduler airflow-webserver
```

### HTTP 상태

```powershell
Invoke-RestMethod http://localhost:8088/api/health |
    ConvertTo-Json -Depth 10

(Invoke-WebRequest -UseBasicParsing http://localhost:8088).StatusCode

Invoke-RestMethod http://localhost:8765/health |
    ConvertTo-Json -Depth 10
```

RAG health의 주요 판정값:

```text
status = ok
warm = true
corpus_chunks > 0
embedding_backend = local:BAAI/bge-m3  # 로컬 설정 예시
reranker_backend = local:BAAI/bge-reranker-v2-m3(cpu)
```

`corpus_chunks=0`이면 서버는 살아 있지만 아직 검색할 인덱스가 없는 것이다. 레거시 import와
`jobis_rag` 성공 여부를 확인한다.

### 자원 사용량

```powershell
docker stats
```

적재 컨테이너가 약 200% CPU를 사용하는 것은 2 CPU 제한을 채워 쓰는 상태다. 메모리 부족,
컨테이너 재시작, 호스트 전체 응답 불가가 함께 나타나는지를 기준으로 장애 여부를 판단한다.

## 11. RAG 검색 테스트

### 빠른 검색: 리랭킹 끄기

Windows PowerShell 5.1은 `application/json` 응답에 charset이 없으면 UTF-8 한글을 잘못
해석할 수 있다. `Invoke-RestMethod` 결과에서 회사명이 `ã...`처럼 보이면 DB가 깨진 것이
아니므로, 원시 바이트를 UTF-8로 직접 변환하는 다음 방식을 사용한다.

```powershell
$payload = @{
    input = "서울 백엔드 개발자 Java Spring"
    top_k = 3
    evaluate = $false
    use_rerank = $false
} | ConvertTo-Json

$requestBytes = [System.Text.Encoding]::UTF8.GetBytes($payload)

$response = Invoke-WebRequest `
    -UseBasicParsing `
    -Method Post `
    -Uri "http://localhost:8765/search" `
    -ContentType "application/json; charset=utf-8" `
    -Body $requestBytes

$json = [System.Text.Encoding]::UTF8.GetString(
    $response.RawContentStream.ToArray()
)

$result = $json | ConvertFrom-Json

$result.postings |
    Select-Object company, title, score, url |
    Format-List
```

회사명과 공고 제목이 한글로 출력되고 입력 직무·기술과 관련된 공고가 반환되면 검색 경로가
정상이다.

### 리랭킹 포함 검색

위 payload에서 다음 값만 바꾼다.

```powershell
use_rerank = $true
```

로컬 CrossEncoder는 CPU 2코어 제한에서 느릴 수 있다. 현재 개발 환경에서는 상위 후보 3건
리랭킹에 약 54초가 걸린 적이 있으므로, 반복 smoke test는 `false`, 최종 순위 검증은 `true`를
사용한다.

## 12. 애플리케이션 기능 smoke test

브라우저에서 `http://localhost:8088`을 열고 다음 순서로 확인한다.

1. 회원가입 또는 로그인
2. 커리어 대화 메시지 전송
3. 사용자 메시지가 즉시 저장되고 AI 답변 작업이 완료되는지 확인
4. 공고 URL 또는 공고 원문 등록
5. 분석 시작 후 완료/추가 질문 알림 확인
6. 분석 결과의 근거, 역량, 지원 판단 화면 확인

실패하면 브라우저의 일반 오류 문구만 보지 말고 같은 시각의 요청 ID와 다음 로그를 확인한다.

```powershell
cd C:\Users\<사용자>\work\data-airflow
docker compose logs --since 10m backend
docker compose logs --since 10m ai
```

AI health HTTP 200은 프로세스가 준비됐다는 뜻이다. 실제 Codex 호출 성공은 `--models` 또는
실제 분석/대화 완료로 별도 확인한다. 스트리밍 HTTP 200도 연결이 열렸다는 뜻일 뿐이므로 최종
성공 이벤트나 UI 완료 상태까지 확인한다.

## 13. 자동화 테스트

### RAG 단위 테스트

최신 `rag-ingest` 이미지 안에는 필요한 Python 의존성이 들어 있다.

```powershell
cd C:\Users\<사용자>\work\data-airflow

docker run --rm `
    --entrypoint python `
    jobis/rag-ingest:latest `
    -m unittest discover -s tests -p "test_*.py" -v
```

현재 기준으로 provider 선택, GMS 응답 정렬/오류 처리, 로컬 batch 제한, 벡터 프로필 원자성,
RAG 계약을 포함한 24개 테스트가 통과해야 한다.

### Backend + AI + Frontend 소스 검증

Java 17, npm, uv가 설치된 개발 환경에서 실행한다.

```powershell
cd C:\Users\<사용자>\work\data-airflow
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
```

이 스크립트는 Backend 테스트, AI 테스트/구조 검사, Frontend 프로덕션 빌드를 실행한다. 단위
테스트 성공을 실제 Codex/GMS API 호출 성공으로 표현하지 않는다.

## 14. 코드나 환경변수 변경 후 재실행

### 애플리케이션

```powershell
cd C:\Users\<사용자>\work\data-airflow
docker compose up --build -d
```

### RAG 모델/provider/자원 설정

```powershell
cd C:\Users\<사용자>\work\data-airflow\infra\airflow

docker compose build rag-search
docker build `
    -t jobis/rag-ingest:latest `
    -f Dockerfile.rag-ingest `
    ..\..

docker compose up -d --force-recreate rag-search airflow-scheduler
docker compose exec airflow-scheduler airflow dags trigger jobis_rag
```

적재와 검색은 같은 `RAG_EMBED_PROVIDER`, 모델, `RAG_VECTOR_DIMENSIONS`를 사용해야 한다.
불일치하면 서로 다른 벡터 공간을 섞지 않도록 검색 서버가 기동을 거부한다.

### Flyway 마이그레이션만 다시 확인

```powershell
cd C:\Users\<사용자>\work\data-airflow\infra\airflow
docker compose run --rm jobrag-migrate
```

`Successfully validated ... migrations`, `Successfully applied ...` 또는 이미 최신 버전이라는
메시지가 나오면 정상이다. 이 명령이 만든 임의 이름의 컨테이너는 `--rm` 때문에 종료 후 사라진다.

## 15. 중지와 데이터 보존

컨테이너만 중지하고 DB, 모델 캐시, Codex 로그인 상태를 보존하려면 `stop`을 사용한다.

```powershell
cd C:\Users\<사용자>\work\data-airflow
docker compose stop

cd infra\airflow
docker compose stop
```

다시 시작:

```powershell
cd C:\Users\<사용자>\work\data-airflow\infra\airflow
docker compose up -d

cd ..\..
docker compose up -d
```

다음 볼륨에는 복구가 필요한 상태가 있으므로 원인을 모른 채 삭제하지 않는다.

- 서비스 PostgreSQL: `data-airflow_jobiss_postgres_data`
- AI 세션/Codex OAuth: `data-airflow_jobiss_ai_state`
- Airflow/jobrag PostgreSQL: `airflow_pgdata`
- Airflow 로그: `airflow_airflow-logs`
- 크롤 상태/산출물: `jobis-crawl-state`, `jobis-crawl-exports`
- 모델 캐시: `jobis-hf-cache`, `jobis-ocr-paddlex-cache`, `jobis-ocr-paddle-cache`

특히 `docker compose down -v`는 이 데이터를 삭제할 수 있으므로 일반 재시작 절차에서 사용하지
않는다. DB 백업과 복구는 [infra/airflow/BACKUP_RESTORE.md](infra/airflow/BACKUP_RESTORE.md),
배포와 롤백은 [ops/DEPLOYMENT.md](ops/DEPLOYMENT.md)를 따른다.

## 16. 자주 만나는 증상

### `jobis-codex-oauth` 실행 파일을 찾지 못함

Docker 이미지에서는 console script 대신 다음 모듈 진입점을 사용한다.

```powershell
docker compose run --rm --no-deps --entrypoint python `
    ai -m jobis_ai.codex_oauth_adapter.cli --login
```

### DAG trigger 결과가 `queued`

정상적으로 요청이 접수된 상태다. 성공 여부는 Airflow UI 또는 `airflow dags list-runs`에서
`success`까지 확인한다.

### `airflow-init` 또는 `jobrag-migrate`가 종료됨

`Exited (0)`이면 정상적인 일회성 작업 완료다. 0이 아니면 해당 서비스 로그를 확인한다.

### `.env`의 DB 비밀번호를 바꾼 뒤 인증 실패

PostgreSQL 볼륨이 이미 초기화된 뒤 `.env`만 바꿔도 DB 내부 계정 비밀번호는 자동 변경되지
않는다. 기존에 사용한 값을 복원하거나 DB 내부에서 계획적으로 변경한다. 데이터를 확인하지 않고
볼륨을 삭제해서 해결하지 않는다.

### RAG 검색 결과의 한글이 깨짐

PowerShell 5.1 응답 디코딩 문제다. 11장의 `RawContentStream` UTF-8 변환 예제를 사용한다.
DB 원문 손상으로 단정하지 않는다.

### `No such container: laughing_ritchie`

Airflow DockerOperator 또는 `docker compose run --rm`이 만든 임시 컨테이너가 이미 제거된
것이다. 고정된 임의 이름 대신 이미지 필터로 현재 컨테이너 ID를 다시 조회한다.

### GMS 키가 빠르게 소진됨

`infra/airflow/.env`를 로컬 provider로 되돌리고 `rag-search`, `rag-ingest` 이미지를 모두 다시
빌드한 뒤 `jobis_rag`를 실행한다.

```dotenv
RAG_EMBED_PROVIDER=local
RAG_RERANK_PROVIDER=local
GMS_KEY=
```

### 검색은 되지만 새 적재 데이터가 보이지 않음

RAG 적재는 모든 임베딩 계산과 DB 저장이 성공한 뒤 한 번에 새 인덱스를 공개한다. 실행 중에는
이전 성공 인덱스가 계속 검색되며, 새 데이터는 `store_chunks`와 DAG success 이후 반영된다.
