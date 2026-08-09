import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

function source(path: string) {
  return readFileSync(new URL(path, import.meta.url), "utf8");
}

test("에이전트 실행 카드는 완료 아이콘과 단계 상태를 보라색 별·점으로 표현한다", () => {
  const component = source("../src/components/AgentExecutionMap.vue");
  const theme = source("../src/styles/jobis-theme.css");

  assert.match(component, /<Sparkles v-else-if="allComplete"/);
  assert.doesNotMatch(component, /<Check v-else-if="allComplete"/);
  assert.match(component, /class="agent-execution-map__trail"/);
  assert.match(theme, /\.agent-execution-map__trail i \{[\s\S]*?border-radius: 50%/);
  assert.match(theme, /\.agent-execution-map\.compact \{[\s\S]*?background: #fff/);
});

test("대화와 전역 작업 상태는 실제 진행·실패·예상시간 계약을 표시한다", () => {
  const types = source("../src/types.ts");
  const shelf = source("../src/components/ConversationShelf.vue");
  const shell = source("../src/components/AppShell.vue");

  assert.match(types, /aiReplyPending: boolean/);
  assert.match(types, /latestJobFailed: boolean/);
  assert.match(types, /latestMessageRole:/);
  assert.match(types, /estimatedRemainingSeconds: number \| null/);
  assert.match(shelf, /item\.aiReplyPending/);
  assert.match(shelf, /item\.latestJobFailed/);
  assert.match(shelf, /hasUnreadCompletedReply/);
  assert.match(shell, /app-topbar__status-spinner/);
  assert.match(shell, /activeJobEstimate/);
});

test("빈 대화는 자동 생성하지 않고 홈으로 돌아가며 중복 에이전트 산출물을 숨긴다", () => {
  const chat = source("../src/views/ChatView.vue");

  assert.doesNotMatch(chat, /else if \(conversationStatus\.value === "ACTIVE"[\s\S]*?await createConversation\(\)/);
  assert.match(chat, /router\.replace\(\{ name: "home", query: \{ focus: "chat" \} \}\)/);
  assert.match(chat, /JOB_DISCOVERY_PLAN: "JOB_RECOMMENDATIONS"/);
  assert.match(chat, /visibleAgentWarnings/);
});

test("답변 생성과 스크롤 복귀는 작성창 위의 점·아래 화살표로 노출한다", () => {
  const chat = source("../src/views/ChatView.vue");
  const theme = source("../src/styles/jobis-theme.css");

  assert.match(chat, /class="chat-generation-dots"/);
  assert.match(chat, /aria-label="최신 메시지로 이동"/);
  assert.match(chat, /showNewMessages\.value = !isNearMessageBottom\(\)/);
  assert.match(theme, /@keyframes chat-dot-bounce/);
});

test("제품명과 파비콘은 JOBIS와 사이드바 펭귄 마크로 고정한다", () => {
  const html = source("../index.html");
  const router = source("../src/router.ts");
  const home = source("../src/views/HomeView.vue");

  assert.match(html, /<title>JOBIS<\/title>/);
  assert.match(html, /href="\/src\/assets\/logo-mark\.png"/);
  assert.match(router, /document\.title = "JOBIS"/);
  assert.doesNotMatch(home, /CAREER COPILOT/);
});

test("저장된 공고의 원문 수정은 구형 분석이 아니라 확인된 V3 재분석으로 연결한다", () => {
  const api = source("../src/api.ts");
  const detail = source("../src/views/PostingDetailView.vue");
  const postings = source("../src/views/PostingsView.vue");

  assert.match(api, /async reanalyzeV3Posting\(/);
  assert.match(api, /entryPoint: "POSTINGS_PAGE"/);
  assert.match(api, /postingId,/);
  assert.match(api, /latestPriorSource\?\.extractionRevision/);
  assert.match(api, /previousSnapshotId:/);
  assert.match(api, /verifiedBy: "USER"/);
  assert.match(detail, /api\.reanalyzeV3Posting\(/);
  assert.match(postings, /api\.reanalyzeV3Posting\(/);
  assert.doesNotMatch(detail, /api\.updatePosting\(/);
  assert.doesNotMatch(postings, /api\.updatePosting\(/);
});

test("채팅 제목은 좌측 흐름에 놓이고 AI 목록 응답은 카드가 아닌 본문 목록으로 표시된다", () => {
  const theme = source("../src/styles/jobis-theme.css");

  assert.doesNotMatch(theme, /\.app-shell--chat \.app-topbar__center/);
  assert.match(theme, /\.app-shell--chat \.app-page-title \{[\s\S]*?text-align: left/);
  assert.match(theme, /\.chat-message--assistant \.agent-rich ul li \{[\s\S]*?border: 0;[\s\S]*?background: transparent/);
});

test("공고 적합도와 로드맵 초안을 분리하고 초안 관계를 그래프로 표시한다", () => {
  const detail = source("../src/views/PostingDetailView.vue");
  const graph = source("../src/components/RoadmapProposalGraph.vue");

  assert.match(detail, /지원 적합도 · 갭 분석/);
  assert.match(detail, /아래 로드맵 초안과는 별도 분석입니다/);
  assert.match(detail, /v3RoadmapRelations/);
  assert.match(detail, /<RoadmapProposalGraph/);
  assert.doesNotMatch(detail, /확정된 커리어 자료가 없어 공고 조건만으로 로드맵/);
  assert.match(graph, /blockingRelationTypes/);
  assert.match(graph, /fromOperationId/);
  assert.match(graph, /toOperationId/);
  assert.match(graph, /필수 순서/);
  assert.match(graph, /추천·보조 연결/);
});
