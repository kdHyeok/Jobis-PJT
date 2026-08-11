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

검색은 `query`, `status`, `sort`, `direction`, `page`, `size`, `archived`를 지원합니다. 이미 지도에 반영된 공고는 그래프 근거 보존을 위해 직접 삭제하지 못합니다.

## 분석 작업

- `GET /api/analysis-jobs`
- `GET /api/analysis-jobs/{jobId}`
- `POST /api/analysis-jobs/{jobId}/retry`
- `POST /api/analysis-jobs/{jobId}/questions/{questionId}/answer`
- `POST /api/analysis-jobs/{jobId}/approve`
- `POST /api/analysis-jobs/{jobId}/reject`

분석 결과의 지원 판단은 `APPLY_NOW`, `STRENGTHEN_THEN_APPLY`, `ALTERNATIVE_FIRST` 중 하나입니다. 변경안 상태는 `PROPOSED → APPROVED | REJECTED`입니다.
작업 응답의 `stage`, `stageMessage`로 원문 정리·AI 비교·변경안 검증 등 현재 단계를 표시합니다.
작업 상태가 `WAITING_FOR_INPUT`이면 `pendingQuestion`에 질문과 2~4개의 선택지가 포함됩니다. 답변 본문은 `{"value":"선택지 value"}`이며, 서버는 제공된 선택지인지 확인한 뒤 같은 작업을 `QUEUED`로 되돌립니다.

## 커리어 지도와 증빙

- `GET /api/career-map`
- `POST /api/career-map/nodes/{nodeId}/self-confirm`
- `GET /api/career-map/nodes/{nodeId}/evidence`
- `POST /api/career-map/nodes/{nodeId}/evidence`
- `GET /api/evidence/{evidenceId}`
- `POST /api/evidence/{evidenceId}/retry`

기반 노드만 자기 확인할 수 있습니다. 그 외 단계의 검증 상태는 `PENDING`, `RUNNING`, `VERIFIED`, `NEEDS_WORK`, `REJECTED`, `FAILED`입니다.

## 알림과 상태

- `GET /api/notifications`
- `POST /api/notifications/{notificationId}/read`
- `POST /api/notifications/read-all`
- `GET /api/health`

분석 추가 확인, 분석 완료, 커리어 자료 검토 준비, 그래프 반영, 증빙 검토 완료 알림의 payload에는 해당 화면으로 돌아갈 수 있는 작업·질문·자료·노드 ID가 포함됩니다.
