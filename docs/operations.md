# JOBISS 운영 가이드

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

백업은 서비스 DB와 다른 저장소에 보관하고, 정기적으로 별도 스테이징 DB에 `pg_restore --clean --if-exists` 복원 테스트를 수행합니다.

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

## 장애 대응

- AI 장애: 대화 메시지와 작업은 보존됩니다. 공급자 복구 후 실패 작업을 화면에서 재시도합니다.
- 커리어 파편화 장애: 원본 자료는 보존되며 공급자 복구 후 자료 단위로 재시도합니다.
- 역량 검증 장애: 이미 저장된 질문과 답변은 유지하고, 동일 답변의 중복 처리를 막은 상태에서 재시도합니다.
- DB 장애: 헬스체크가 실패하므로 새 트래픽을 받지 않고 복구 또는 백업 복원을 수행합니다.
- 잘못된 그래프 제안: 승인 전 거절합니다. 이미 승인된 데이터는 직접 SQL로 수정하지 말고 보정 마이그레이션을 작성합니다.
- 배포 장애: 이전 이미지 버전으로 애플리케이션을 되돌리되, 적용된 DB 마이그레이션은 임의로 삭제하지 않습니다.

## 현재 의도된 경계

- URL만으로 공고를 수집하지 않습니다. 저작권·로그인·로봇 정책 문제를 피하기 위해 사용자가 URL과 원문을 함께 제공합니다.
- 증빙 URL의 내용을 읽었다고 가정하지 않습니다. 검증 가능한 설명과 결과를 사용자가 함께 제출해야 합니다.
- 합격을 보장하지 않고 준비도와 보완 방향만 제공합니다.
- 공용 추천 카탈로그에는 공고 원문과 사용자 식별 정보를 저장하지 않습니다. 원본 URL이 없거나 오래 갱신되지 않은 공고는 운영 정책에 따라 비활성화해야 합니다.
