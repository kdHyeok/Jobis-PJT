# JOBIS 일일 수집 파이프라인 (Airflow + PostgreSQL/pgvector)

`DATA/` 크롤러와 이미지형 공고 OCR을 책임별 네 DAG로 실행해 `jobrag` DB에 적재한다:

- `job_postings` — 원본 공고 테이블 (`DATA/export_postgres.py` + psql)
- `postings`/`chunks` — RAG 검색용 벡터 테이블 (현재 브랜치 `RAG/run_ingest_additive.py`)
- `rag-search` — 같은 DB를 조회해 최신 AI의 `POST /search` 계약을 제공하는 검색 서버

```text
jobis_collect (매일 KST 03:00, crawl x5 병렬)
  → jobis_load_postgres (완료/X + OCR 대기/O 선적재)
  → jobis_ocr (PostgreSQL 큐 OCR x5, pool로 1개씩)
  → jobis_rag (DB 완료행만 export → BGE-M3 증분 임베딩)
```

- 수집 정기 스케줄은 `jobis_collect`에만 있다. 다음 DAG들은 Dataset 이벤트로 연결되며,
  `jobis_ocr`만 재시도 시각이 된 행을 회수하기 위해 30분 주기도 함께 사용한다.
- 수집 일부가 실패해도 사용 가능한 사이트별 상태를 OCR 단계로 넘기는 기존 additive 정책을 유지한다.
- PaddleOCR는 CPU·메모리 사용량이 커서 `ocr_pool` 1 slot로 직렬 실행한다.
- 첫 OCR 때만 한국어 검출·인식 모델을 다운로드하며, 이후에는 전용 캐시 볼륨을 재사용한다.
- `jobis_collect`의 `max_new`와 `max_candidates`, `jobis_ocr`의 `ocr_max` 파라미터로
  단계별 상한을 조절한다. `max_candidates=0`은 후보 검사 수를 제한하지 않는다.

| 발행 DAG | Dataset | 다음 DAG |
|---|---|---|
| `jobis_collect` | `jobis://raw-site-postings` | `jobis_load_postgres` |
| `jobis_load_postgres` | `jobis://job-postings-loaded` | `jobis_ocr` |
| `jobis_load_postgres` | `jobis://postings-ready-for-rag` | `jobis_rag` |
| `jobis_ocr` (OCR 성공 건이 있을 때만) | `jobis://postings-ready-for-rag` | `jobis_rag` |
| `jobis_rag` | `jobis://rag-index-ready` | 최종 산출물 |

## 최초 1회 설정 (배포 서버)

```bash
cd infra/airflow
cp .env.example .env        # 값 전부 교체
docker compose build

# DockerOperator가 실행할 최신 RAG 적재 이미지
docker build -t jobis/rag-ingest:latest \
  -f Dockerfile.rag-ingest ../..

docker compose up -d
```

- Airflow UI: `http://<서버>:8081` (admin / .env의 AIRFLOW_ADMIN_PASSWORD)
- RAG 검색 API: `http://<서버>:8765/health`, `POST http://<서버>:8765/search`
- AI를 호스트에서 실행하면 `RAG_PROVIDER=http`, `RAG_SEARCH_URL=http://127.0.0.1:8765`로 연결한다.
- `rag-search`는 요청마다 DB 청크 서명을 확인하므로 Airflow 적재 뒤 BM25 인덱스도 자동 갱신된다.
- `jobis_collect`가 매일 KST 03:00 실행되고 나머지 세 DAG를 순서대로 자동 트리거한다.
- 처음 배포하면 네 DAG를 모두 unpause해야 한다. 이전 `jobis_daily_ingest`는 실행 이력 확인용으로
  남지만 더 이상 DAG 파일에서 정의하거나 스케줄하지 않는다.
- `jobrag-migrate`가 `migrations/jobrag`의 Flyway 이력을 먼저 적용하며, 실패하면
  scheduler/webserver가 시작되지 않는다. RAG 태스크는 더 이상 실행 때마다 `schema.sql`을
  적용하지 않는다.
- 초기 전량 적재를 건너뛰려면 `RAG/`의 기존 덤프를 시딩:
  `psql $JOBRAG_PG_DSN -f all_job_postings_postgres.sql` (job_postings)
  — RAG 쪽 postings/chunks는 첫 DAG 런이 전량 임베딩한다 (CPU 수 시간, 1회성).
  이후는 content_hash 덕에 신규분만 임베딩된다.

## 수동 실행과 단계별 재실행

- 전체 흐름 테스트: `jobis_collect`를 수동 Trigger한다. 성공한 Dataset 이벤트가 뒤의 세 DAG를
  자동으로 연결한다.
- OCR부터 재실행: `jobis_ocr`을 수동 Trigger하면 DB 대기 행 처리 후 RAG까지 이어진다.
- DB 적재부터 재실행: `jobis_load_postgres`를 수동 Trigger하면 OCR과 RAG까지 이어진다.
- RAG만 재실행: `jobis_rag`을 수동 Trigger한다.

소량 테스트 권장값:

`jobis_collect`:

```json
{"max_new": 1, "max_candidates": 20}
```

`jobis_ocr`:

```json
{
  "ocr_max": 1,
  "ocr_max_attempts": 2,
  "ocr_retry_base_minutes": 60,
  "ocr_lease_minutes": 60
}
```

OCR 작업 상태는 `job_postings.ocr_status`에 `pending → processing → succeeded`로 기록한다.
실패하면 60분부터 지수 백오프로 `retry_wait`에 들어가며 누적 2회 실패 시 `dead`가 된다.
`FOR UPDATE SKIP LOCKED`와 lease/worker ID로 여러 워커가 같은 행을 동시에 처리하지 않는다.
Airflow 재시도는 워커/DB 장애에, `ocr_attempt_count`는 개별 공고 OCR 실패에 사용한다.
`jobis_ocr`는 DB 적재 Dataset 이벤트에는 즉시 실행되고, 그 외에는 30분마다 retry 대상만 확인한다.
주기 실행에서 OCR 성공 건이 0건이면 결과 발행 태스크를 `skipped` 처리해 RAG를 불필요하게 다시 실행하지 않는다.

각 DAG의 Graph는 내부 태스크 책임을 보여주고, Airflow의 Datasets/DAG Dependencies 화면은
네 DAG 사이의 연결을 보여준다. 현재 크롤러는 고정된 상태·export 파일을 사용하므로, 앞 단계와
뒤 단계가 실행 중일 때 같은 DAG를 다시 수동 Trigger하지 않는다.

### 레거시 SQLite 일회성 import

`jobis_legacy_import`는 스케줄이 없는 수동 DAG다. `.env`의
`JOBIS_LEGACY_SQLITE_PATH` 파일을 읽기 전용으로 마운트하고 다음 순서로 실행한다.

```text
validate_sqlite → prepare_import → import_postgres → verify_import
```

- 본문 완료(`X`)와 OCR 대기(`O`) 행을 모두 import한다. 이미지 없는 대기 행은 `dead`로 표시한다.
- 임시 staging 테이블에서 건수·PK·OCR 상태를 검증한 뒤 `job_postings`에 UPSERT한다.
- 기존 PostgreSQL 값은 우선 보존하고, 기존 본문이 비어 있을 때만 레거시 본문으로 보강한다.
- 검증 성공 시 `jobis://job-postings-loaded`와 `jobis://postings-ready-for-rag`를 함께 발행해 각각 `jobis_ocr`와 `jobis_rag`로 이어진다.
- 재실행해도 같은 `(source, posting_id)`가 추가로 생기지 않지만, 운영에서는 검증 완료 후
  한 번만 Trigger하고 DAG를 pause 상태로 되돌린다.

기본 저장소 파일을 쓰지 않을 경우 `.env`에 compose 파일 기준 상대 경로나 절대 경로를 지정한다.

```dotenv
JOBIS_LEGACY_SQLITE_PATH=/srv/jobis-import/all_job_postings.db
```

실행 전 `scripts/backup-databases.sh`로 백업하고, Airflow UI에서 `jobis_legacy_import`만
unpause한 뒤 Trigger한다. `verify_import`까지 성공한 것을 확인한 후 다시 pause한다.

## 크롤러 코드 업데이트 반영

Airflow 이미지는 빌드할 때 저장소의 `DATA/`를 `/opt/jobis/DATA/`로 복사한다. 따라서
`develop`의 크롤러 변경을 병합한 뒤에는 스케줄러와 웹서버 이미지를 다시 빌드하고
두 서비스만 재생성한다. DB와 크롤 상태는 네임드 볼륨에 있으므로 이 명령으로 지워지지 않는다.

```bash
cd infra/airflow
docker compose build airflow-scheduler airflow-webserver
docker compose up -d --no-deps airflow-scheduler airflow-webserver
docker compose exec -T airflow-scheduler \
  airflow pools set ocr_pool 1 "PaddleOCR tasks run one at a time"
```

## DB 마이그레이션과 백업·복구

- 스키마 변경은 적용된 파일을 고치지 말고 `migrations/jobrag/V2__...sql`처럼 새 버전으로
  추가한다.
- 매일 및 배포 직전에 PostgreSQL custom-format 덤프와 checksum, manifest를 별도
  저장소에 남긴다.
- 복구는 운영 DB를 덮지 않고 새 DB에 먼저 수행한 뒤 `JOBRAG_DB_NAME`으로 전환한다.

실행 명령, 보존 정책, 복구 훈련 및 롤백 순서는 [BACKUP_RESTORE.md](BACKUP_RESTORE.md)에
정리되어 있다.

## 상태가 사는 곳 (지우면 안 되는 볼륨)

| 볼륨 | 내용 |
|---|---|
| `pgdata` | 모든 DB (airflow 메타 + jobrag) |
| `jobis-crawl-state` | 크롤러 이어받기 상태 (사이트별 SQLite) |
| `jobis-crawl-exports` | merge 산출물 JSON (rag-ingest가 읽음) |
| `jobis-hf-cache` | BGE-M3 모델 캐시 (~2.3GB, 최초 1회 다운로드) |
| `jobis-ocr-paddlex-cache` | PaddleOCR 3 모델 캐시 |
| `jobis-ocr-paddle-cache` | PaddleOCR 구버전 호환 모델 캐시 |

## 아직 안 넣은 것

- RAG 검색 서빙: jobrag DB에 접속하는 별도 서비스로 이 compose에 추가 예정.
