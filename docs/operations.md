# JOBIS 운영 가이드

## 출시 전 필수값

- 실제 HTTPS 도메인과 TLS 종료 프록시
- 서로 다른 PostgreSQL 마이그레이션/앱 비밀번호
- 32바이트 이상의 JWT 비밀값과 AI 내부 공유 비밀값
- Anthropic API 키와 비용 한도
- `ALLOWED_ORIGINS`의 정확한 서비스 도메인
- PostgreSQL 영구 볼륨의 백업 위치

운영에서는 `.env.production.example`을 복사해 사용하되 `.env`를 저장소에 커밋하지 않습니다.

## 기동과 확인

```powershell
docker compose up --build -d
docker compose ps
```

외부 프록시를 통해 `GET /api/health`가 `status=ok`, `database=ok`를 반환해야 트래픽을 연결합니다. AI 서버의 `/health`에는 실제 공급자 이름이 나타나야 합니다.

Flyway 마이그레이션은 백엔드 기동 전에 마이그레이션 전용 계정으로 자동 실행됩니다. 실패한 마이그레이션 상태에서는 새 버전으로 트래픽을 전환하지 않습니다.

## 운영자 계정

운영자 권한을 부여하는 공개 HTTP API는 만들지 않습니다. DB 관리자 또는
마이그레이션 계정으로 본인 확인이 끝난 기존 계정만 승격합니다.

```sql
UPDATE users
SET account_role = 'OPERATOR'
WHERE email = 'operator@example.com';
```

운영자 화면에서는 유사 공고의 병합·분리·보류, 병합 되돌리기, 역량 검증
이의제기 승인·반려를 처리합니다. 모든 결정은 감사 테이블에 남고 사용자에게
검토 결과 알림이 생성됩니다. 운영자 판정은 사용자 공고 분석의 완료 경로를
막지 않습니다.

## 백업

배포 전과 매일 PostgreSQL custom-format 백업을 생성합니다.

```bash
pg_dump --format=custom --no-owner --file=jobiss-$(date +%F).dump "$DATABASE_URL"
```

백업은 서비스 DB와 다른 저장소에 보관하고, 정기적으로 별도 스테이징 DB에 `pg_restore --clean --if-exists` 복원 테스트를 수행합니다. 탈퇴 계정이 포함된 백업은 생성 시점부터 최대 30일 안에 만료되도록 백업 저장소의 lifecycle 정책을 설정합니다. 애플리케이션의 삭제 worker는 외부 백업을 직접 삭제할 수 없으므로 이 정책과 복원 훈련은 운영 인프라의 필수 조건입니다.

## 모니터링

- 프론트 프록시의 4xx/5xx 비율
- 백엔드 `/api/health`와 응답 지연
- `analysis_jobs`, `chat_reply_jobs`, `career_sources`, `evidence_verification_queue`의 오래된 `RUNNING` 작업
- `competency_assessment_sessions`의 오래된 `IN_PROGRESS` 세션과 AI 검증 실패율
- AI 공급자 429/5xx와 요청 시간
- `posting_duplicate_candidates`의 오래된 `OPEN`/`ON_HOLD` 건과
  `competency_assessment_sessions.review_status='REQUESTED'` 대기 건
- DB 연결 수, 디스크 사용량과 백업 성공 여부

모든 백엔드 응답의 `X-Request-ID`를 장애 제보와 서버 로그의 연관 키로 사용합니다. 로그에는 공고 원문, 인증 쿠키, API 키를 기록하지 않습니다.

AI 서버 PowerShell에는 `JOBISS_AI_PROGRESS` 로그가 표시됩니다.

- `operation`, `request_id`, `phase`, `attempt`, `state`
- 실행 중에는 10초 간격의 `elapsed_seconds`, 완료 시 토큰·비용
- 공고, 이력서, 프롬프트, 부분 JSON 내용은 기록하지 않음

## 단일 AI 런타임

현재 운영 경로는 `JOBIS AI :8400` 하나입니다. 채팅과 공고 수집·확인·적합도·프로젝트·역량·
로드맵 workflow가 같은 프로세스와 공급자 설정을 사용합니다. 별도 8500 서버, `shadow` 모드,
provider 결과 비교 UI는 D047에서 폐기했습니다.

- Spring 설정의 AI base URL과 shared secret은 한 쌍만 유지합니다.
- DB의 신규 검증형 분석은 `analysis_provider='UNIFIED'`로 저장합니다.
- `LEGACY`는 과거 분석을 읽는 호환 값이며 신규 검증형 source job에 사용하지 않습니다.
- 과거 `ai_provider_comparisons` 기록은 감사 이력으로 보존하지만 현재 실행 분기에는 사용하지 않습니다.
- 장애 시 작업과 질문·응답은 Spring/PostgreSQL에 남으며, 공급자 복구 후 해당 작업을 명시적으로
  재시도합니다. 공급자 이름을 사용자 화면의 상태로 노출하지 않습니다.

## 장애 대응

- AI 장애: 대화 메시지와 작업은 보존됩니다. 공급자 복구 후 실패 작업을 화면에서 재시도합니다.
- 커리어 파편화 장애: 원본 자료는 보존되며 공급자 복구 후 자료 단위로 재시도합니다.
- 역량 검증 장애: 이미 저장된 질문과 답변은 유지하고, 동일 답변의 중복 처리를 막은 상태에서 재시도합니다.
- DB 장애: 헬스체크가 실패하므로 새 트래픽을 받지 않고 복구 또는 백업 복원을 수행합니다.
- 잘못된 그래프 제안: 승인 전 거절합니다. 이미 승인된 데이터는 직접 SQL로 수정하지 말고 보정 마이그레이션을 작성합니다.
- 배포 장애: 이전 이미지 버전으로 애플리케이션을 되돌리되, 적용된 DB 마이그레이션은 임의로 삭제하지 않습니다.

## 통합 분석 역량 후보 검토와 그래프 발행 경계

운영자 화면의 `역량 사전` 탭에는 통합 분석에서 공용 그래프에 매핑되지 않은 후보가 나타납니다.

- `신규 승인`: 새로운 canonical 역량 후보로 staging합니다.
- `기존 연결`: 이미 존재하는 canonical key와 연결 후보로 staging합니다.
- `분리 필요`: 한 후보에 여러 수행 범위가 섞여 있어 다시 분해해야 함을 기록합니다.
- `보류`·`반려`: 사용자 로드맵의 검토 중 표시는 유지하되 공용 역량으로 승격하지 않습니다.

`새 그래프 버전 발행`은 승인 후보와 감사 이력을 versioned release bundle로 묶는 작업입니다. 이 버튼만 눌렀다고 활성 공용 그래프가 바뀐 것은 아닙니다. 외부 `C:\jobiss-capability-graph-lab`의 운영자 API에서 `preview → import → activate`를 순서대로 수행해야 하며, activation 전 계약·출처·순환 검증을 통과해야 합니다. 잘못 활성화한 버전은 `rollback`으로 직전 활성 버전으로 되돌립니다. 소비자 조회 API는 activation 전까지 기존 version/hash를 계속 반환해야 합니다.

## 인증·URL 수집 보안 확인

- 로그아웃은 access cookie 삭제와 함께 해당 사용자의 `auth_version`을 증가시킵니다. 로그아웃 전에 발급된 access token은 재사용할 수 없어야 합니다.
- 운영 환경 시작 시 기본 또는 짧은 JWT/AI secret, 동일한 DB app/migrator 비밀번호, 개발용 저장소 암호화 키, 부정확한 CORS·메일 설정을 거부합니다.
- URL 수집은 DNS 검증 결과의 public IP에 실제 연결을 고정하며 redirect마다 다시 검증합니다. DNS 검증과 socket 연결 사이에 주소가 바뀌어도 사설망으로 연결되어서는 안 됩니다.
- access token은 2시간, 회전형 refresh token은 기본 14일, `로그인 유지` 선택 시 30일입니다. 사용된 refresh token의 재사용이 탐지되면 같은 token family 전체를 폐기합니다.
- 공고·이력서 원문과 신규 검증 답변은 application-level AES-GCM으로 저장하고, 공고 중복 판정은 별도 HMAC fingerprint를 사용합니다. 두 키는 DB와 서로 분리된 비밀 저장소에서 관리하고 같은 값을 사용하지 않습니다.
- 이 기능 배포 전에 기존 평문 원문의 일회성 backfill을 수행해야 합니다. 암호화 키를 먼저 배포한 뒤 재암호화하고, 표본 복호화와 fingerprint 재계산을 검증하기 전에는 평문 column을 제거하지 않습니다.
- 민감 원문을 포함하지 않는 AI 진단 기록은 30일, 운영 판정·보안 감사 기록은 1년 보존합니다. `OperationalRetentionWorker` 실행 건수와 실패를 모니터링합니다.
- 계정 탈퇴는 즉시 로그인과 사용자 접근을 차단한 뒤 삭제 요청 영수증을 반환합니다. 운영 DB 물리 삭제 worker가 완료되기 전까지 `account_deletion_requests` 상태를 감사하며, 외부 백업은 위 30일 lifecycle을 따릅니다.

## 현재 의도된 경계

- 공개된 http/https 공고 URL은 서버가 제한된 크기의 HTML/텍스트만 가져옵니다. 내부망 주소와 비텍스트 응답은 차단하고, 담당 업무·지원 조건 신호가 부족하면 저장하지 않은 채 사용자에게 원문 붙여넣기를 요청합니다. 로그인·동적 렌더링·수집 차단 사이트는 자동 우회하지 않습니다.
- 증빙 URL의 내용을 읽었다고 가정하지 않습니다. 검증 가능한 설명과 결과를 사용자가 함께 제출해야 합니다.
- 합격을 보장하지 않고 준비도와 보완 방향만 제공합니다.
- 공용 추천 카탈로그에는 공고 원문과 사용자 식별 정보를 저장하지 않습니다. 원본 URL이 없거나 오래 갱신되지 않은 공고는 운영 정책에 따라 비활성화해야 합니다.
