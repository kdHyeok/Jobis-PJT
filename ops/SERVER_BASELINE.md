# JOBISS 운영 서버 기준선

확인 시각: 2026-08-12 KST
대상: `ssh ssafy_ec2` (`ip-172-26-14-250`)

이 파일에는 비밀값을 기록하지 않는다. 값이 아니라 구조와 검증 상태만 남긴다.
아래는 **컨테이너 전환(cutover) 완료 후** 읽기 전용 점검 결과다.

## 호스트

| 항목 | 값 |
|---|---|
| OS | Ubuntu 24.04.3 LTS (kernel `7.0.0-1010-aws`) |
| CPU / 메모리 | 4 vCPU / 15 GiB (점검 시 사용 6.4 GiB, 가용 9.2 GiB) |
| 스왑 | `/swapfile` 16 GiB |
| 디스크 | `/dev/root` 309 GB, 34% 사용. `/`·`/mnt`·`/opt/jobis`가 **같은 파일시스템** |
| Docker | Engine 29.6.2 / Compose v5.3.1 |

> 루트 `AGENTS.md`의 "가용 메모리 약 2GB·스왑 0" 서술은 이 실측과 다르다. CI 스테이지
> 병렬화를 금지한 근거가 그 수치였으므로, 재검토가 필요하면 Infra MR로 다룬다.

## 현재 운영 상태

애플리케이션 컨테이너 6개가 **같은 커밋 SHA 태그**로 실행 중이다(점검 시 2일 경과).
운영 Compose는 `network_mode: host`이므로 컨테이너가 개별 포트를 발행하지 않는다.

| 컨테이너 | 포트 | 상태 |
|---|---|---|
| `jobis-frontend` | 8088 | healthy |
| `jobis-backend` | 8080 | healthy |
| `jobis-ai` | 8000 | healthy |
| `jobis-rag-search` | 8765 | healthy |
| `jobis-airflow-webserver` | 8081 | healthy |
| `jobis-airflow-scheduler` | — | running |

- Jenkins: 컨테이너 `jenkins/jenkins:lts-jdk21`, `127.0.0.1:9090`에만 바인딩, 호스트 Docker socket 공유
- Nginx 1.24.0 (Ubuntu): `server_name i15c202.p.ssafy.io`, 443 TLS(Certbot)
  - `/jenkins/` → `127.0.0.1:9090`
  - `/airflow/` → `127.0.0.1:8081` (`/etc/jobis/nginx-airflow.location.conf`)
  - `/` → `/etc/jobis/nginx-active-upstream.conf` → `127.0.0.1:8088` (제어 include)
- `jobis-fake-ai`는 더 이상 실행되지 않는다(전환 시 정지). 8500 별도 AI 경로도 없다.

**배포 지연 주의**: 실행 중인 SHA보다 최신인 SHA의 이미지가 이미 서버에 존재한다.
develop CI가 빌드했으나 아직 승격·배포되지 않은 상태다. `docker ps`의 이미지 태그와
`docker images` 목록을 비교해 확인한다.

## DB와 백업

PostgreSQL은 **호스트 설치 단일 인스턴스**다. 컨테이너로 옮기지 않았다 — loopback 계약을
넓히지 않기 위해서다.

| 항목 | 값 |
|---|---|
| 버전 | 16.14 (Ubuntu 16.14-0ubuntu0.24.04.1) |
| 접근 | `127.0.0.1:5432` loopback 전용 (audit `[PASS] database remains loopback-only`) |

| DB | owner | 용도 |
|---|---|---|
| `jobiss_v2` | `jobiss_migrator` | 서비스 정본. `jobiss_app`에는 Tc 권한만 부여 |
| `jobrag` | `jobrag` | 벡터 색인 (pgvector 확장) |
| `airflow` | `airflow` | Airflow 메타 DB |
| `jobiss` | `jobis` | 레거시. 복구용으로 보존, 사용하지 않음 |

> **로컬 개발은 PostgreSQL 17 컨테이너를 쓴다.** 운영은 호스트 16.14이므로 메이저 버전이
> 다르다. 17 전용 문법으로 마이그레이션을 쓰면 로컬 CI를 통과하고 배포에서 실패한다.
> `Release migration gate`가 운영 덤프로 검증하므로 완전히 무방비는 아니지만, 그 게이트가
> 도는 컨테이너 버전도 함께 확인할 필요가 있다.

- 백업 경로 `/mnt/jobis-backups/`. 일일 백업과 월간 복원 훈련 timer 모두 활성화 확인
  (`[PASS] systemd timer enabled: jobis-db-backup.timer`, `jobis-db-restore-drill.timer`)
- 레거시 dump는 `/mnt/jobis-backups/legacy-db`에 checksum·manifest와 함께 보존

## 해소된 사전 준비

전환 전 기준선이 "release 차단"으로 남겨 둔 9개 항목 중 8개가 해소됐다.
근거는 `sudo /usr/local/sbin/audit-jobis-server` 출력이다.

| 항목 | 근거 |
|---|---|
| develop SHA 이미지 생성 | 6종 이미지가 SHA 태그로 서버에 존재 |
| Flyway 적용 | `[PASS] Flyway schema includes legacy import audit contract` |
| `jobiss` → `jobiss_v2` 이관 | `[PASS] legacy jobiss import audit record` |
| 백업·복원 timer 활성화 | `[PASS] systemd timer enabled` ×2 |
| Airflow/jobrag DB bootstrap | `[PASS] PostgreSQL connectivity: airflow, jobrag` |
| 릴리스 자산 SHA 동기화 | `[PASS] deployed release asset checksums` |
| develop/master MR 병합 | develop 파이프라인이 이미지를 빌드·게시하고 있음 |
| RAG 검색 가동 | `jobis-rag-search` healthy, `[PASS] AI-to-RAG route` |

기타 사전 세팅(유지): `/etc/jobis/jobis-v2.env` root:root 0600, Codex OAuth 상태 파일
`/var/lib/jobis-ai/codex/auth.json`, `jobis-deploy` 비-root 사용자와 최소 sudoers,
Nginx 원본 timestamp 백업.

## 남은 제약

점검 결과는 `failures=0 warnings=3`이다. 둘은 같은 원인이고, 하나는 점검 방식이다.

1. **별도 백업 파일시스템 미연결** — `/mnt`와 `/opt/jobis`가 같은 root 파일시스템이라
   `JOBIS_BACKUP_REQUIRE_SEPARATE_FILESYSTEM=false` 저하 모드로 운영한다. 논리 오류와
   운영자 실수는 dump로 복구되지만 **호스트 디스크 장애는 보호되지 않는다.** 이 서버는
   별도 EBS/API 권한을 제공하지 않는다. 별도 마운트나 외부 object storage가 제공되면
   즉시 `true`로 되돌린다.
   - `[WARN] same-disk degraded backup mode`
   - `[WARN] pipeline backups share the application disk`
2. **SHA 미지정 점검** — `[WARN] release SHA was not supplied`는 결함이 아니라 인자 없이
   상시 점검을 돌린 결과다. 배포 직전에는 `audit-jobis-server <SHA> predeploy`로 실행해
   경고를 실패로 승격시킨다.

## 디스크 사용 참고

이미지가 디스크의 상당 부분을 차지한다. 같은 이미지의 여러 SHA 태그는 레이어를 공유하므로
태그 수만큼 늘지는 않지만, 승격이 누적되면 정리가 필요하다.

| 이미지 | 크기 |
|---|---|
| `jobis-airflow` | 4.62 GB |
| `jobis-rag-ingest` | 2.29 GB |
| `jobis-rag-search` | 2.21 GB |
| `jobis-ai` | 347 MB |
| `jobis-backend` | 320 MB |
| `jobis-frontend` | 79.6 MB |

자동 이미지 정리는 넣지 않았다. 롤백 대상 이미지를 지울 위험이 있으므로, 필요할 때
보존할 SHA를 확인한 뒤 수동으로 정리한다.
