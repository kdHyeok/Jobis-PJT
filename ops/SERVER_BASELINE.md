# JOBISS 운영 서버 기준선

확인 시각: 2026-08-05 KST
대상: `ssh ssafy_ec2` (`ip-172-26-14-250`)

이 파일에는 비밀값을 기록하지 않는다. 값이 아니라 구조와 검증 상태만 남긴다.
아래 상태는 컨테이너 전환 전 읽기 전용 점검 스냅샷이다. 현재 저장소의 목표 계약은
Airflow/RAG를 운영 Compose에 포함하므로, 릴리스 전에 자산 동기화와 재감사가 필요하다.

## 현재 운영 상태

- `jobis-backend`: 기존 `jobis` Compose 프로젝트, host network, 8080, 실행 유지
- `jobis-fake-ai`: 기존 `jobis` Compose 프로젝트, host network, 8000, 실행 유지
- Jenkins: 컨테이너, `127.0.0.1:9090`, 호스트 Docker socket 공유
- Nginx: 80/443, `/jenkins/`는 9090, 앱 `/`는 제어 include를 통해 기존 8080 유지
- PostgreSQL 16: `127.0.0.1:5432`
- RAG 8765: 현재 listener 없음. v2 env는 `RAG_PROVIDER=null`

기존 컨테이너와 이미지, 비활성 systemd unit은 삭제하지 않았다. 실제 최초 cutover에서만 기존
컨테이너를 stop/rename하고 fake AI를 stop한다. 실패하면 다시 시작하며 자동 이미지 정리는 없다.

## DB와 백업

- 레거시 DB `jobiss`: owner `jobis`, 기존 16개 테이블, 변경 없이 유지
- 신규 DB `jobiss_v2`: owner `jobiss_migrator`, 사전 준비 시점에는 빈 DB
- 신규 역할 `jobiss_migrator`, `jobiss_app`: login 가능, superuser/createdb/createrole/bypassrls 없음
- 레거시 dump: `/mnt/jobis-backups/legacy-db`, checksum과 격리 복원(16개 테이블) 검증 완료
- `/mnt`와 `/opt/jobis`는 현재 같은 root filesystem

현재 dump는 논리 오류·실수 복구에는 쓸 수 있지만 호스트 디스크 장애를 막지 못한다. 별도 EBS
마운트 또는 외부 object storage가 연결되고
`JOBIS_BACKUP_REQUIRE_SEPARATE_FILESYSTEM=true`가 되기 전에는 release 감사를 통과할 수 없다.

## 완료된 사전 세팅

- `/etc/jobis/jobis.env` 보존, `/etc/jobis/jobis-v2.env` 별도 생성(root:root 0600)
- `/var/lib/jobis-ai/codex/auth.json`을 값 출력 없이 신규 영속 경로로 보존 복사
- `/opt/jobis`, `/usr/local/sbin`에 Compose·배포·백업·감사·이관 자산 설치
- `jobis-deploy` 비-root 사용자, SSH 공개키, 최소 sudoers 검증
- Nginx 설정 원본을 timestamp 파일로 보존하고 controlled upstream include 활성화
- HTTPS 앱 200, Jenkins 경로 403(익명 접근 차단 응답), 기존 세 컨테이너 실행 상태 확인

## 의도적으로 남겨 둔 release 차단 항목

1. 별도 백업 파일시스템 미연결
2. develop SHA 이미지 미생성
3. Flyway V27 미적용
4. `jobiss` → `jobiss_v2` 트랜잭션 이관 미실행
5. DB 백업/월간 복원 timer 미활성화
6. develop/master MR 미병합
7. Airflow/jobrag DB bootstrap 및 Flyway V1~V3 미적용
8. `jobis-deploy-known-hosts`와 서버 릴리스 자산 SHA 동기화 미검증
9. RAG 검색·실제 LLM runtime probe 미검증

`sudo /usr/local/sbin/audit-jobis-server`는 위 항목을 사전 준비 단계에서는 경고한다.
`audit-jobis-server <SHA> predeploy`는 이를 실패로 바꾸므로 빈 DB나 미검증 이미지로 cutover할
수 없다.
