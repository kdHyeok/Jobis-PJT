# JOBIS 일일 수집 파이프라인 (Airflow + PostgreSQL/pgvector)

`DATA/` 크롤러를 매일 실행해 `jobrag` DB에 두 갈래로 적재한다:

- `job_postings` — 원본 공고 테이블 (`DATA/export_postgres.py` + psql)
- `postings`/`chunks` — RAG 검색용 벡터 테이블 (feat/ai/rag의 `run_ingest_additive.py`)

```
crawl x5 (병렬) → merge → ┬ load_job_postings   (Airflow 이미지 안에서 psql)
                          └ rag_ingest          (jobis/rag-ingest 컨테이너)
```

## 최초 1회 설정 (배포 서버)

```bash
cd infra/airflow
cp .env.example .env        # 값 전부 교체
docker compose build

# RAG 이미지: 소스가 feat/ai/rag 브랜치에 있어 그 체크아웃을 컨텍스트로 빌드
git worktree add /srv/jobis-rag feat/ai/rag
docker build -t jobis/rag-ingest:latest \
  -f Dockerfile.rag-ingest /srv/jobis-rag

docker compose up -d
```

- Airflow UI: `http://<서버>:8081` (admin / .env의 AIRFLOW_ADMIN_PASSWORD)
- DAG `jobis_daily_ingest`가 매일 KST 03:00 실행 (수동 실행: UI에서 Trigger)
- 초기 전량 적재를 건너뛰려면 feat/ai/rag의 기존 덤프를 시딩:
  `psql $JOBRAG_PG_DSN -f all_job_postings_postgres.sql` (job_postings)
  — RAG 쪽 postings/chunks는 첫 DAG 런이 전량 임베딩한다 (CPU 수 시간, 1회성).
  이후는 content_hash 덕에 신규분만 임베딩된다.

## 크롤러 코드 업데이트 반영

Airflow 이미지는 빌드할 때 저장소의 `DATA/`를 `/opt/jobis/DATA/`로 복사한다. 따라서
`develop`의 크롤러 변경을 병합한 뒤에는 스케줄러와 웹서버 이미지를 다시 빌드하고
두 서비스만 재생성한다. DB와 크롤 상태는 네임드 볼륨에 있으므로 이 명령으로 지워지지 않는다.

```bash
cd infra/airflow
docker compose build airflow-scheduler airflow-webserver
docker compose up -d --no-deps airflow-scheduler airflow-webserver
```

## 상태가 사는 곳 (지우면 안 되는 볼륨)

| 볼륨 | 내용 |
|---|---|
| `pgdata` | 모든 DB (airflow 메타 + jobrag) |
| `jobis-crawl-state` | 크롤러 이어받기 상태 (사이트별 SQLite) |
| `jobis-crawl-exports` | merge 산출물 JSON (rag-ingest가 읽음) |
| `jobis-hf-cache` | BGE-M3 모델 캐시 (~2.3GB, 최초 1회 다운로드) |

## 아직 안 넣은 것

- OCR(`enrich_ocr.py`, paddle): 이미지 준비 후 crawl과 merge 사이 태스크로 추가.
  그전까지 이미지형 공고(`need_ocr='O'`)는 사이트별 원본에 남지만, 본문이 비어 있어
  통합본과 PostgreSQL·RAG 적재에서는 제외된다. OCR 성공 후 다음 실행에 포함된다.
- RAG 검색 서빙: jobrag DB에 접속하는 별도 서비스로 이 compose에 추가 예정.
