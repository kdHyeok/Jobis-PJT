# 전달 — 대화 진행 이벤트에 발화 본문(`message`) 추가 (D153, 2026-08-04)

백엔드·프론트 팀 전달용. AI 파트에서 세 층을 함께 고쳤고, 각 파트 소유 코드의 변경분은
아래가 전부다. 문제 있으면 되돌려도 된다 — AI 쪽은 필드를 안 읽는 소비자에게 무해하다.

## 무엇이 왜 바뀌었나

한 턴에 여러 에이전트가 순차로 답을 만드는데(이력서 정리 → 적합도 판정 → 로드맵 안내),
지금까지 발화가 **턴 끝에 한 덩어리**로만 도착했다. 진행 이벤트(`/v1/chat/stream`)에는
"완료 · 4.2초" 같은 과정 라벨만 있었고 발화 본문이 없었기 때문이다. 이제 `agent_end`
진행 이벤트에 그 담당의 발화 본문이 `message`(최대 4000자, 없으면 빈 문자열)로 실린다.
최종 합본 메시지와 `replySources` 는 **그대로다** — 기존 소비자는 아무것도 바꿀 필요 없다.

## 백엔드 변경 (2개 파일, 이미 적용·테스트 통과)

- `analysis/AiContracts.java` — `ProgressStep` 레코드에 `String message` 추가.
- `analysis/AiAnalysisClient.java` — 채팅 스트림 파서가 `event.path("message")` 를 읽어 채움.
- 저장은 기존 경로 그대로: `ChatReplyWorker.recordChatProgress` 가 스텝 전체를 JSON 으로
  `chat_reply_agent_events.event_data` 에 넣는다(스키마 변경 없음). `stage_message` 는
  종전대로 라벨·detail 만 쓴다(한 줄 표시라 본문을 넣지 않는다).

## 프론트 변경 (3개 파일, 이미 적용·vue-tsc 통과)

- `types.ts` — `ChatAgentStep.message?: string | null`.
- `ChatView.vue` — `agentTurns` 가 `message` 를 `speech` 로 모아, 진행 중 `agent-stream`
  말풍선에 과정 라벨과 별개 문단으로 그린다. 끝난 턴은 기존처럼 접히고 최종 답변이
  `replySources` 로 나뉘어 뜨므로 중복 표시는 없다.
- `styles/base.css` — `.agent-turn__speech` (본문색·pre-wrap).

## 검증

AI `pytest -q` 758건 · 백엔드 `compileJava`+`test` · 프론트 `vue-tsc` 전부 통과.
결정 기록: `AI/docs/decisions.md` D153.
