# jobrag/Airflow DB 백업·복구 운영 절차

이 절차의 목표는 컨테이너를 보존하는 것이 아니라 PostgreSQL 논리 덤프와 스키마
이력을 별도 저장소에 축적하는 것이다. `pgdata` 볼륨 복사만으로 백업을 대신하지 않는다.

## 운영 원칙

- `infra/airflow/migrations/jobrag/V*__*.sql`은 한 번 반영한 뒤 수정하지 않는다. 변경은
  다음 번호의 새 파일로 추가한다.
- 배포 직전과 매일 1회 `jobrag` 및 Airflow 메타 DB를 custom-format으로 백업한다.
- 백업 경로는 저장소와 Docker 호스트 디스크가 아닌 별도 디스크/NAS/object storage로
  지정한다. 덤프와 `.env`를 Git에 커밋하지 않는다.
- 매월 최소 1회 복구 훈련을 실행한다. `pg_restore --list`만 성공한 것은 복구 성공이 아니다.
- 운영 DB를 바로 덮어쓰지 않는다. 새 DB로 복구하고 검증한 뒤 DSN을 전환한다.

## 1. 마이그레이션

`docker compose up -d` 시 `jobrag-migrate`가 먼저 완료되어야 Airflow scheduler와
webserver가 시작된다. 기존 `schema.sql` 기반 DB는 Flyway version `0`으로 baseline한 뒤
idempotent V1을 적용한다. 이후 새 변경은 예를 들어 아래처럼 추가한다.

```text
infra/airflow/migrations/jobrag/
├── V1__create_jobrag_schema.sql
└── V2__add_posting_status.sql
```

수동 확인:

```bash
cd infra/airflow
docker compose run --rm jobrag-migrate info
docker compose run --rm jobrag-migrate migrate
```

외부 PostgreSQL을 쓸 때는 관리자가 대상 DB에 `vector` 확장을 먼저 설치하고, Flyway
계정이 해당 DB 스키마 객체를 생성·변경할 수 있게 권한을 부여한다.

## 2. 백업

```bash
cd infra/airflow
BACKUP_DIR=/mnt/jobis-backups RETENTION_DAYS=14 \
  bash ./scripts/backup-databases.sh
```

각 실행은 다음 파일을 만든다.

- `<jobrag-db>-<UTC>.dump`, `airflow-<UTC>.dump`: `pg_dump --format=custom`
- 각 덤프의 `.sha256`
- Git SHA, PostgreSQL/Flyway 버전, 주요 테이블 건수를 담은 manifest와 checksum

cron 예시(실제 절대 경로와 로그 경로로 교체):

```cron
15 2 * * * cd /srv/jobis/infra/airflow && BACKUP_DIR=/mnt/jobis-backups RETENTION_DAYS=14 bash ./scripts/backup-databases.sh >> /var/log/jobis-db-backup.log 2>&1
```

## 3. 복구 훈련

백업 파일을 임시 DB로 복구하고 Flyway 적용, 필수 테이블, 행 수, chunk 외래키를 확인한
뒤 임시 DB를 자동 삭제한다.

```bash
cd infra/airflow
bash ./scripts/restore-jobrag-test.sh /mnt/jobis-backups/jobrag-20260803T020000Z.dump
```

## 4. 실제 장애 복구

1. Airflow DAG를 pause하고 scheduler 등 DB writer를 중지한다.
2. 손상된 현재 상태도 별도 이름으로 백업한다.
3. 운영 DB와 다른 새 이름으로 복구한다. 스크립트는 `jobrag`, `airflow`, `postgres`를
   대상으로 지정하면 거부하며, 기존 DB도 덮어쓰지 않는다.

   ```bash
   bash ./scripts/restore-jobrag-to-new-db.sh \
     /mnt/jobis-backups/jobrag-20260803T020000Z.dump \
     jobrag_recovered_20260803
   ```

4. 새 DB에서 manifest 대비 행 수, 애플리케이션 조회, RAG 검색, 최근 공고/OCR 본문을
   확인한다.
5. `.env`의 `JOBRAG_DB_NAME=jobrag_recovered_20260803`으로 바꾸고 아래 서비스를
   재생성한다.

   ```bash
   docker compose up -d jobrag-migrate airflow-scheduler airflow-webserver
   ```

6. smoke test 통과 후 DAG를 다시 활성화한다. 이전 DB는 즉시 삭제하지 말고 롤백 기간
   동안 읽기 금지 상태로 보관한다. 문제가 생기면 `JOBRAG_DB_NAME`을 이전 값으로 되돌려
   서비스를 재생성한다.

Airflow 메타 DB도 동일하게 새 DB로 복구하는 것이 원칙이지만, 서비스 DSN 변경과
Airflow migration 순서가 함께 필요하므로 장애 시점의 버전으로 컨테이너를 고정한 뒤
복구한다. DAG 코드와 크롤 원본 상태 볼륨은 DB 덤프와 별도로 백업해야 한다.
