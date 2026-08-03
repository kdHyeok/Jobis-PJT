# JOBISS API 계약

모든 변경 요청은 CSRF 헤더가 필요하고, 인증 API와 헬스체크를 제외한 엔드포인트는 HttpOnly 인증 쿠키가 필요합니다.

## 인증

- `GET /api/auth/csrf`
- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/me`

## 대화

- `GET /api/conversations`
- `POST /api/conversations`
- `GET /api/conversations/{conversationId}`
- `POST /api/conversations/{conversationId}/messages`
- `POST /api/conversations/{conversationId}/archive`
- `DELETE /api/conversations/{conversationId}`

메시지는 자유 텍스트 또는 공고 첨부를 포함합니다. `clientMessageId`는 중복 제출을 막습니다.

## 대화 답변 작업

- `GET /api/chat-reply-jobs/{jobId}`
- `GET /api/chat-reply-jobs/conversation/{conversationId}`
- `POST /api/chat-reply-jobs/{jobId}/retry`

메시지 전송 응답에는 저장된 사용자 메시지와 `chatReplyJobId`가 포함됩니다. AI 답변은 작업 성공 후 별도 메시지로 추가됩니다.

## 커리어 저장소

- `POST /api/career-sources`
- `GET /api/career-sources`
- `GET /api/career-sources/{sourceId}`
- `POST /api/career-sources/{sourceId}/retry`
- `POST /api/career-sources/{sourceId}/confirm`
- `DELETE /api/career-sources/{sourceId}`
- `GET /api/career-fragments`
- `PATCH /api/career-fragments/{fragmentId}`
- `POST /api/career-fragments/merge`
- `POST /api/career-fragments/{fragmentId}/archive`
- `POST /api/career-fragments/{fragmentId}/restore`
- `DELETE /api/career-fragments/{fragmentId}`

원본 자료는 `QUEUED → RUNNING → REVIEW_READY → CONFIRMED` 흐름을 가지며 실패 시 `FAILED`가 됩니다. 제안 조각은 사용자가 선택해 확정하기 전까지 대화와 공고 분석 근거로 사용하지 않습니다.

## 채용 공고

- `POST /api/job-postings`
- `GET /api/job-postings`
- `GET /api/job-postings/search`
- `GET /api/job-postings/{postingId}`
- `PATCH /api/job-postings/{postingId}`
- `POST /api/job-postings/{postingId}/archive`
- `POST /api/job-postings/{postingId}/restore`
- `DELETE /api/job-postings/{postingId}`
- `GET /api/job-postings/{postingId}/alternatives`

검색은 `query`, `status`, `sort`, `direction`, `page`, `size`, `archived`를 지원합니다. 이미 지도에 반영된 공고는 그래프 근거 보존을 위해 직접 삭제하지 못합니다.
`alternatives`는 다른 사용자의 원문이나 개인 분석을 반환하지 않고, 공용 카탈로그에 게시된 회사·직무·원본 URL·경력 조건과 현재 사용자의 역량 기준 점수만 반환합니다.

## 분석 작업

- `GET /api/analysis-jobs`
- `GET /api/analysis-jobs/{jobId}`
- `POST /api/analysis-jobs/{jobId}/retry`
- `POST /api/analysis-jobs/{jobId}/questions/{questionId}/answer`
- `POST /api/analysis-jobs/{jobId}/approve`
- `POST /api/analysis-jobs/{jobId}/reject`

분석 결과의 지원 판단은 `APPLY_NOW`, `STRENGTHEN_THEN_APPLY`, `ALTERNATIVE_FIRST` 중 하나입니다. AI는 판단 자료를 추출하고, 최종 값은 백엔드가 검증된 필수 역량 충족률과 경력 조건으로 결정합니다. 분석안 상태는 `PROPOSED → APPROVED | REJECTED`입니다.
작업 응답의 `stage`, `stageMessage`로 원문 정리·AI 비교·변경안 검증 등 현재 단계를 표시합니다.
작업 상태가 `WAITING_FOR_INPUT`이면 `pendingQuestion`에 질문과 2~4개의 선택지가 포함됩니다. 답변 본문은 `{"value":"선택지 value"}`이며, 서버는 제공된 선택지인지 확인한 뒤 같은 작업을 `QUEUED`로 되돌립니다.

백엔드는 AI 서버의 `POST /v1/analyses/stream`을 우선 호출합니다. 응답은 한 줄에
완전한 JSON 하나를 담는 `application/x-ndjson`이며 이벤트는
`RUN_STARTED → STAGE_UPDATED* → RESULT | ERROR` 순서입니다. AI 서버가 아직
스트림 경로를 제공하지 않아 404 또는 405를 반환할 때만
`POST /v1/analyses`로 자동 폴백합니다. 상세 계약과 예시는
[AI 에이전트 연동 가이드](./ai-agent-integration.md)에 있습니다.

AI의 `competencyProposal`은 다음 자료만 제안합니다.

- 공고 경로: `job.primaryTrack`, 경력 조건의 필수·우대 여부,
  최소·최대 개월 수와 근거 원문
- 표준 역량: `canonicalKey`, 이름, 분야, 종류, 단계, 범위, 요구 수준,
  `roadmapEligible`, `verificationMethod`
- 공고 조건: `REQUIRED`, `PREFERRED`, `RESPONSIBILITY`
- 회사 맞춤 프로젝트: 목표, 도메인 맥락, 필요 역량, 결과물, 완료 기준

`roadmapEligible=false`인 책임감·몰입도·원활한 소통 같은 정성 조건은 분석 참고
정보로만 반환하며 로드맵, 준비도, 회사 맞춤 프로젝트 조건에서는 제외합니다. 공고별
분야와 단계는 해당 분석 시점의 요구사항 스냅샷으로 저장합니다. 역량의 기술 분류와
화면 경로는 분리하며, 백엔드 공고에서 요구한 CI/CD·클라우드 역량도 로드맵에서는
해당 공고의 `BACKEND` 경로에 배치합니다.

AI는 로드맵 노드·간선·좌표·순서를 만들지 않습니다. `approve`는 분석 자료를 목표 공고에 추가하고 새 로드맵 초안을 생성하지만 현재 공개 버전은 즉시 변경하지 않습니다.

## 버전형 로드맵

- `GET /api/roadmap`
- `POST /api/roadmap/draft`
- `POST /api/roadmap/draft/apply`
- `DELETE /api/roadmap/targets/{postingId}`
- `POST /api/roadmap/reset`

`GET`은 현재 공개 버전과 적용 전 초안을 함께 반환합니다. `draft`는 활성 목표 공고와 표준 역량을 기준으로 최신 초안을 다시 만들며, `draft/apply`가 성공해야 새 버전이 공개됩니다. 새 공고로 분기가 바뀌어도 완료 상태는 노드 위치가 아니라 사용자의 표준 역량 ID에 보존됩니다.

로드맵은 회사마다 별도 경로를 만들지 않고 주 직무별 통합 경로를 반환합니다. 경력
제한이 없는 기회 뒤에는 `관련 {직무} 취업`, 필수 경력 개월 수, 경력직 기회가
순서대로 연결됩니다. `RoadmapNode.requirementKinds`는 한 역량 노드가 각 공고에서
`REQUIRED`인지 `PREFERRED`인지 보존하므로, 공고 필터를 바꾸면 동일 노드를 필수
퀘스트 또는 보너스 퀘스트로 표시할 수 있습니다.

## 커리어 역량과 증빙

- `GET /api/career-map`
- `POST /api/career-map/nodes/{nodeId}/self-confirm`
- `GET /api/career-map/nodes/{nodeId}/assessment`
- `POST /api/career-map/nodes/{nodeId}/assessment`
- `POST /api/competency-assessments/{sessionId}/answers`
- `POST /api/competency-assessments/{sessionId}/review`
- `GET /api/career-map/nodes/{nodeId}/evidence`
- `POST /api/career-map/nodes/{nodeId}/evidence`
- `GET /api/evidence/{evidenceId}`
- `POST /api/evidence/{evidenceId}/retry`

기반 역량만 자기 확인할 수 있습니다. 일반 기술은 `IN_PROGRESS → PASSED | NEEDS_STUDY` 상태의 개인 AI 검증을 사용합니다. 개념·코드·상황 적용을 모두 확인하며 한 시도에서 최대 5문항을 냅니다. 같은 역량·같은 요구 수준에서 최근 30일 안에 60점 이상 받은 유형은 재도전 세션의 `retainedScores`로 이월하고 부족한 유형만 새 문제로 확인합니다. 회사 맞춤 프로젝트 등의 결과물 증빙 상태는 `PENDING`, `RUNNING`, `VERIFIED`, `NEEDS_WORK`, `REJECTED`, `FAILED`입니다.

검증 질문과 채점 결과는 현재 노드의 `coreCriteria`와 장기 목표를 위한
`futureExtensions`를 분리합니다. `NEEDS_STUDY` 결과는 이의제기할 수 있고,
운영자 승인 시 해당 역량과 연결된 로드맵 진행 상태가 완료됩니다.

## 운영자 검토

- `GET /api/operator/posting-duplicates`
- `POST /api/operator/posting-duplicates/{candidateId}/resolve`
- `POST /api/operator/posting-duplicates/audits/{auditId}/rollback`
- `GET /api/operator/assessment-reviews`
- `POST /api/operator/assessment-reviews/{sessionId}/resolve`

계정의 `accountRole`이 `OPERATOR`인 사용자만 사용할 수 있습니다. 공고 중복은
`MERGE | SEPARATE | HOLD`, 역량 이의제기는 `APPROVE | REJECT`로 처리합니다.
병합은 사용자별 공고 원문과 분석 이력을 삭제하지 않고 대표 카탈로그 연결만
바꾸며, 감사 기록을 통해 되돌릴 수 있습니다.

## 목표 프로필

- `GET /api/profile/goals`
- `PUT /api/profile/goals`

`currentGoalPostingId`는 사용자가 소유하고 분석이 완료된 활성 공고만 지정할 수
있습니다. `finalGoalText`는 장기 목표를 자유 텍스트로 저장합니다. 현재 목표는
역량 검증의 핵심 범위와 난이도를 정하고, 최종 목표는 현재 역량 범위를 침범하지
않는 심화 맥락으로만 AI에 전달됩니다.

## 알림과 상태

- `GET /api/notifications`
- `POST /api/notifications/{notificationId}/read`
- `POST /api/notifications/read-all`
- `GET /api/health`

분석 추가 확인, 분석 완료, 커리어 자료 검토 준비, 그래프 반영, 증빙 검토 완료 알림의 payload에는 해당 화면으로 돌아갈 수 있는 작업·질문·자료·노드 ID가 포함됩니다.
