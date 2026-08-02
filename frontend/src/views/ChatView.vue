<script setup lang="ts">
import {
  ArrowRight,
  BriefcaseBusiness,
  Check,
  ChevronDown,
  CircleAlert,
  CircleHelp,
  FilePlus2,
  LoaderCircle,
  MessageCircleMore,
  Paperclip,
  Plus,
  RefreshCw,
  Send,
  X,
} from "@lucide/vue";
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api } from "@/api";
import AnalysisProgressWheel from "@/components/AnalysisProgressWheel.vue";
import type {
  AnalysisJob,
  ChatReplyJob,
  Conversation,
  ConversationMessage,
  ConversationSummary,
} from "@/types";

const route = useRoute();
const router = useRouter();
const conversations = ref<ConversationSummary[]>([]);
const conversation = ref<Conversation | null>(null);
const message = ref("");
const loading = ref(true);
const sending = ref(false);
const error = ref("");
const showPosting = ref(false);
const sourceType = ref<"TEXT" | "URL">("TEXT");
const sourceUrl = ref("");
const rawText = ref("");
const analysisById = ref<Record<string, AnalysisJob>>({});
const answerSelections = ref<Record<string, string>>({});
const chatJobsById = ref<Record<string, ChatReplyJob>>({});
const actionJobId = ref<string | null>(null);
const messageList = ref<HTMLElement | null>(null);
let pollTimer: number | null = null;

const activeJobs = computed(() =>
  Object.values(analysisById.value).filter((item) =>
    ["QUEUED", "RUNNING"].includes(item.status),
  ),
);

const activeChatJobs = computed(() =>
  Object.values(chatJobsById.value).filter((item) =>
    ["QUEUED", "RUNNING"].includes(item.status),
  ),
);

const analysisMessageIds = computed(() => {
  const seen = new Set<string>();
  const messageIds = new Set<string>();
  const messages = [...(conversation.value?.messages ?? [])].reverse();
  for (const item of messages) {
    if (item.analysisJobId && !seen.has(item.analysisJobId)) {
      seen.add(item.analysisJobId);
      messageIds.add(item.id);
    }
  }
  return messageIds;
});

function messageJob(item: ConversationMessage): AnalysisJob | null {
  return item.analysisJobId ? analysisById.value[item.analysisJobId] ?? null : null;
}

function chatJobForMessage(item: ConversationMessage): ChatReplyJob | null {
  return (
    Object.values(chatJobsById.value).find(
      (job) => job.triggerMessageId === item.id,
    ) ?? null
  );
}

// AI 응답 metadata.replySources — 문장별 화자(도구 render vs 대화형 LLM). 오라우팅 디버깅용 배지.
type ReplySource = { agent: string; channel: string; text?: string };

const CHANNEL_LABEL: Record<string, string> = {
  tool_render: "도구+렌더",
  agent_llm: "대화형 LLM",
  attachment_ack: "첨부 확인",
  lead: "계획 설명",
  rule_note: "규칙",
  consent_gate: "동의 질문",
  notice: "안내",
};

function replySources(item: ConversationMessage): ReplySource[] {
  const raw = (item.metadata as { replySources?: unknown } | null)?.replySources;
  return Array.isArray(raw) ? (raw as ReplySource[]) : [];
}

function sourceLabel(source: ReplySource): string {
  const channel = CHANNEL_LABEL[source.channel] ?? source.channel;
  return source.agent && source.agent !== "orchestrator"
    ? `${source.agent} · ${channel}`
    : channel;
}

// AI 응답 metadata.progress — 턴 내부 진행 타임라인(플래너→실행 계획→에이전트→판정 노드).
type ProgressStep = {
  step: string;
  label: string;
  detail?: string;
  elapsedMs?: number | null;
};

function progressSteps(item: ConversationMessage): ProgressStep[] {
  const raw = (item.metadata as { progress?: unknown } | null)?.progress;
  return Array.isArray(raw) ? (raw as ProgressStep[]) : [];
}

function stepTime(step: ProgressStep): string {
  return step.elapsedMs == null ? "" : `${(step.elapsedMs / 1000).toFixed(1)}s`;
}

function verdictLabel(verdict?: string) {
  if (verdict === "APPLY_NOW") return "지금 지원";
  if (verdict === "STRENGTHEN_THEN_APPLY") return "보강 후 지원";
  if (verdict === "ALTERNATIVE_FIRST") return "대체 공고 우선";
  return "분석 완료";
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat("ko-KR", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

async function scrollToBottom() {
  await nextTick();
  messageList.value?.scrollTo({
    top: messageList.value.scrollHeight,
    behavior: "smooth",
  });
}

async function loadConversations(preferredId?: string) {
  conversations.value = await api.conversations();
  const selected =
    preferredId ??
    conversation.value?.id ??
    conversations.value.find((item) => item.status === "ACTIVE")?.id;
  if (selected) {
    await openConversation(selected);
  } else {
    await createConversation();
  }
}

async function createConversation() {
  error.value = "";
  const created = await api.createConversation();
  conversation.value = created;
  await refreshConversationList();
  await scrollToBottom();
}

async function refreshConversationList() {
  conversations.value = await api.conversations();
}

async function openConversation(id: string) {
  conversation.value = await api.conversation(id);
  await hydrateJobs();
  await scrollToBottom();
}

async function hydrateJobs() {
  const ids = new Set(
    (conversation.value?.messages ?? [])
      .map((item) => item.analysisJobId)
      .filter((id): id is string => Boolean(id)),
  );
  const queryId = typeof route.query.analysisJobId === "string"
    ? route.query.analysisJobId
    : null;
  if (queryId) ids.add(queryId);
  await Promise.all(
    [...ids].map(async (id) => {
      try {
        analysisById.value[id] = await api.analysisJob(id);
      } catch {
        // 다른 대화의 삭제된 작업은 현재 화면을 막지 않는다.
      }
    }),
  );
  const chatJobs = await api.chatReplyJobs(conversation.value?.id ?? "");
  chatJobsById.value = Object.fromEntries(chatJobs.map((job) => [job.id, job]));
  schedulePoll();
}

function schedulePoll() {
  if (pollTimer) window.clearTimeout(pollTimer);
  if (activeJobs.value.length === 0 && activeChatJobs.value.length === 0) return;
  pollTimer = window.setTimeout(pollJobs, 2500);
}

async function pollJobs() {
  const ids = activeJobs.value.map((item) => item.id);
  const chatIds = activeChatJobs.value.map((item) => item.id);
  await Promise.all(
    [
      ...ids.map(async (id) => {
        try {
          analysisById.value[id] = await api.analysisJob(id);
        } catch {
          // 다음 폴링에서 복구한다.
        }
      }),
      ...chatIds.map(async (id) => {
        try {
          chatJobsById.value[id] = await api.chatReplyJob(id);
        } catch {
          // 다음 폴링에서 복구한다.
        }
      }),
    ],
  );
  if (conversation.value) {
    conversation.value = await api.conversation(conversation.value.id);
  }
  schedulePoll();
}

async function sendText() {
  const content = message.value.trim();
  if (!content || !conversation.value || sending.value) return;
  const conversationId = conversation.value.id;
  const optimisticId = `local-${crypto.randomUUID()}`;
  const optimistic: ConversationMessage = {
    id: optimisticId,
    role: "USER",
    kind: "TEXT",
    content,
    postingId: null,
    analysisJobId: null,
    metadata: { optimistic: true },
    createdAt: new Date().toISOString(),
  };
  conversation.value.messages.push(optimistic);
  error.value = "";
  message.value = "";
  sending.value = true;
  await scrollToBottom();
  try {
    const result = await api.sendMessage(conversationId, content);
    if (conversation.value?.id === conversationId) {
      const index = conversation.value.messages.findIndex(
        (item) => item.id === optimisticId,
      );
      const savedMessage = {
        ...result.userMessage,
        metadata: {
          ...result.userMessage.metadata,
          chatReplyJobId: result.chatReplyJobId,
        },
      };
      if (index >= 0) conversation.value.messages.splice(index, 1, savedMessage);
      else conversation.value.messages.push(savedMessage);
    }
    if (result.chatReplyJobId) {
      chatJobsById.value[result.chatReplyJobId] = await api.chatReplyJob(
        result.chatReplyJobId,
      );
      schedulePoll();
    }
    await refreshConversationList();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "메시지를 보내지 못했습니다.";
    if (conversation.value?.id === conversationId) {
      try {
        conversation.value = await api.conversation(conversationId);
        await hydrateJobs();
      } catch {
        message.value = content;
        conversation.value.messages = conversation.value.messages.filter(
          (item) => item.id !== optimisticId,
        );
      }
    }
  } finally {
    sending.value = false;
    await scrollToBottom();
  }
}

async function retryChat(job: ChatReplyJob) {
  actionJobId.value = job.id;
  error.value = "";
  try {
    await api.retryChatReply(job.id);
    chatJobsById.value[job.id] = await api.chatReplyJob(job.id);
    schedulePoll();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "AI 답변을 재시도하지 못했습니다.";
  } finally {
    actionJobId.value = null;
  }
}

async function attachPosting() {
  if (!conversation.value || rawText.value.trim().length < 20) return;
  sending.value = true;
  error.value = "";
  try {
    const title = sourceUrl.value
      ? `채용 공고를 분석해 주세요: ${sourceUrl.value}`
      : "이 채용 공고를 분석해서 제 커리어 지도와 비교해 주세요.";
    const result = await api.sendMessage(conversation.value.id, title, {
      sourceType: sourceType.value,
      sourceUrl: sourceType.value === "URL" ? sourceUrl.value.trim() : null,
      rawText: rawText.value.trim(),
    });
    if (result.analysisJobId) {
      analysisById.value[result.analysisJobId] = await api.analysisJob(
        result.analysisJobId,
      );
    }
    showPosting.value = false;
    sourceUrl.value = "";
    rawText.value = "";
    await openConversation(conversation.value.id);
    await refreshConversationList();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "공고를 등록하지 못했습니다.";
  } finally {
    sending.value = false;
  }
}

async function retry(job: AnalysisJob) {
  actionJobId.value = job.id;
  error.value = "";
  try {
    await api.retryAnalysis(job.id);
    analysisById.value[job.id] = await api.analysisJob(job.id);
    schedulePoll();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "재시도하지 못했습니다.";
  } finally {
    actionJobId.value = null;
  }
}

async function answerAnalysisQuestion(job: AnalysisJob) {
  const question = job.pendingQuestion;
  const value = answerSelections.value[job.id];
  if (!question || !value) return;
  actionJobId.value = job.id;
  error.value = "";
  try {
    await api.answerAnalysisQuestion(job.id, question.id, value);
    delete answerSelections.value[job.id];
    analysisById.value[job.id] = await api.analysisJob(job.id);
    if (conversation.value) {
      conversation.value = await api.conversation(conversation.value.id);
    }
    schedulePoll();
    await scrollToBottom();
  } catch (cause) {
    error.value =
      cause instanceof Error ? cause.message : "답변을 반영하지 못했습니다.";
  } finally {
    actionJobId.value = null;
  }
}

async function approve(job: AnalysisJob) {
  actionJobId.value = job.id;
  error.value = "";
  try {
    await api.approveAnalysis(job.id);
    analysisById.value[job.id] = await api.analysisJob(job.id);
    await router.push({ name: "map" });
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "변경안을 반영하지 못했습니다.";
  } finally {
    actionJobId.value = null;
  }
}

async function reject(job: AnalysisJob) {
  if (!window.confirm("이 변경안을 거절할까요? 공고와 분석 기록은 저장됩니다.")) return;
  actionJobId.value = job.id;
  error.value = "";
  try {
    await api.rejectAnalysis(job.id);
    analysisById.value[job.id] = await api.analysisJob(job.id);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "변경안을 거절하지 못했습니다.";
  } finally {
    actionJobId.value = null;
  }
}

function onComposerKeydown(event: KeyboardEvent) {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    void sendText();
  }
}

watch(
  () => route.query.analysisJobId,
  async (id) => {
    if (typeof id === "string") {
      try {
        analysisById.value[id] = await api.analysisJob(id);
      } catch (cause) {
        error.value = cause instanceof Error ? cause.message : "분석 결과를 찾지 못했습니다.";
      }
    }
  },
);

watch(
  () => route.query.new,
  async (value, previous) => {
    if (typeof value === "string" && value !== previous && !loading.value) {
      try {
        await createConversation();
      } catch (cause) {
        error.value = cause instanceof Error ? cause.message : "새 대화를 만들지 못했습니다.";
      }
    }
  },
);

onMounted(async () => {
  try {
    await loadConversations();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "대화를 불러오지 못했습니다.";
  } finally {
    loading.value = false;
  }
});

onBeforeUnmount(() => {
  if (pollTimer) window.clearTimeout(pollTimer);
});
</script>

<template>
  <main class="chat-workspace">
    <aside class="conversation-sidebar">
      <div class="conversation-sidebar__top">
        <div>
          <p class="eyebrow">CONVERSATIONS</p>
          <h1>커리어 대화</h1>
        </div>
        <button class="icon-button" type="button" aria-label="새 대화" @click="createConversation">
          <Plus :size="20" />
        </button>
      </div>
      <button
        v-for="item in conversations"
        :key="item.id"
        class="conversation-link"
        :class="{ active: conversation?.id === item.id }"
        type="button"
        @click="openConversation(item.id)"
      >
        <MessageCircleMore :size="18" />
        <span>
          <strong>{{ item.title }}</strong>
          <small>{{ item.lastMessage || "새 대화" }}</small>
        </span>
        <time>{{ formatTime(item.lastMessageAt) }}</time>
      </button>
      <div v-if="conversations.length === 0 && !loading" class="sidebar-empty">
        첫 대화를 시작해 보세요.
      </div>
    </aside>

    <section class="chat-panel">
      <header class="chat-panel__header">
        <div>
          <p class="eyebrow">CAREER COPILOT</p>
          <h2>{{ conversation?.title ?? "새 커리어 대화" }}</h2>
        </div>
        <span class="ai-state">
          <i />
          대화와 공고 분석 기록이 자동 저장됩니다
        </span>
      </header>

      <div ref="messageList" class="message-list" aria-live="polite">
        <div v-if="loading" class="state-panel">
          <LoaderCircle class="spin" :size="24" />
          대화를 불러오는 중입니다.
        </div>

        <article
          v-for="item in conversation?.messages ?? []"
          :key="item.id"
          class="chat-message"
          :class="`chat-message--${item.role.toLowerCase()}`"
        >
          <div v-if="item.role === 'ASSISTANT'" class="assistant-avatar">
            <img src="/img/jobi-mascot.png" alt="" />
          </div>
          <div class="chat-bubble">
            <p>{{ item.content }}</p>
            <details
              v-if="item.role === 'ASSISTANT' && progressSteps(item).length"
              class="agent-progress"
            >
              <summary>진행 과정 {{ progressSteps(item).length }}단계 보기</summary>
              <ol>
                <li v-for="(step, index) in progressSteps(item)" :key="index">
                  <strong>{{ step.label }}</strong>
                  <span v-if="step.detail">{{ step.detail }}</span>
                  <small v-if="stepTime(step)">{{ stepTime(step) }}</small>
                </li>
              </ol>
            </details>
            <div
              v-if="item.role === 'ASSISTANT' && replySources(item).length"
              class="reply-sources"
            >
              <span
                v-for="(source, index) in replySources(item)"
                :key="index"
                class="reply-source-chip"
                :class="`reply-source-chip--${source.channel}`"
                :title="source.text"
              >
                {{ sourceLabel(source) }}
              </span>
            </div>
            <time>{{ formatTime(item.createdAt) }}</time>

            <section
              v-if="item.analysisJobId && analysisMessageIds.has(item.id) && messageJob(item)"
              class="analysis-card"
              :class="`analysis-card--${messageJob(item)?.status.toLowerCase()}`"
            >
              <template v-if="['QUEUED', 'RUNNING'].includes(messageJob(item)?.status ?? '')">
                <div class="analysis-card__state analysis-card__state--progress">
                  <AnalysisProgressWheel
                    compact
                    :status="messageJob(item)!.status"
                    :stage="messageJob(item)!.stage"
                    :stage-message="messageJob(item)?.stageMessage"
                  />
                </div>
              </template>

              <template
                v-else-if="
                  messageJob(item)?.status === 'WAITING_FOR_INPUT' &&
                  messageJob(item)?.pendingQuestion
                "
              >
                <div class="analysis-card__question">
                  <AnalysisProgressWheel
                    compact
                    :status="messageJob(item)!.status"
                    :stage="messageJob(item)!.stage"
                    :stage-message="messageJob(item)?.stageMessage"
                  />
                  <div class="analysis-card__question-heading">
                    <CircleHelp :size="22" />
                    <div>
                      <small>
                        분석 확인 {{ messageJob(item)?.pendingQuestion?.ordinal }}/3
                      </small>
                      <strong>{{ messageJob(item)?.pendingQuestion?.text }}</strong>
                    </div>
                  </div>
                  <p>{{ messageJob(item)?.pendingQuestion?.reason }}</p>
                  <div class="analysis-question-options analysis-question-options--chat">
                    <button
                      v-for="option in messageJob(item)?.pendingQuestion?.options ?? []"
                      :key="option.value"
                      type="button"
                      :class="{
                        selected:
                          answerSelections[messageJob(item)!.id] === option.value,
                      }"
                      @click="
                        answerSelections[messageJob(item)!.id] = option.value
                      "
                    >
                      <span>
                        <strong>{{ option.label }}</strong>
                        <small>{{ option.description }}</small>
                      </span>
                      <i><Check :size="14" /></i>
                    </button>
                  </div>
                  <button
                    class="press-button press-button--primary"
                    type="button"
                    :disabled="
                      !answerSelections[messageJob(item)!.id] ||
                      actionJobId === messageJob(item)!.id
                    "
                    @click="answerAnalysisQuestion(messageJob(item)!)"
                  >
                    <LoaderCircle
                      v-if="actionJobId === messageJob(item)!.id"
                      class="spin"
                      :size="17"
                    />
                    <Check v-else :size="17" />
                    답변하고 분석 계속하기
                  </button>
                </div>
              </template>

              <template v-else-if="messageJob(item)?.status === 'FAILED'">
                <div class="analysis-card__state analysis-card__state--error">
                  <CircleAlert :size="22" />
                  <div>
                    <strong>분석을 완료하지 못했습니다</strong>
                    <span>{{ messageJob(item)?.errorMessage }}</span>
                  </div>
                </div>
                <button
                  v-if="(messageJob(item)?.attemptCount ?? 3) < 3"
                  class="press-button press-button--secondary"
                  type="button"
                  :disabled="actionJobId === item.analysisJobId"
                  @click="retry(messageJob(item)!)"
                >
                  <RefreshCw :size="17" />
                  다시 분석
                </button>
              </template>

              <template v-else-if="messageJob(item)?.status === 'SUCCEEDED'">
                <div class="analysis-verdict">
                  <span>{{ verdictLabel(messageJob(item)?.result?.evaluation?.verdict) }}</span>
                  <h3>{{ messageJob(item)?.result?.evaluation?.summary }}</h3>
                  <ul>
                    <li
                      v-for="reason in messageJob(item)?.result?.evaluation?.reasons ?? []"
                      :key="reason"
                    >
                      {{ reason }}
                    </li>
                  </ul>
                </div>

                <details v-if="messageJob(item)?.proposal" class="proposal-details">
                  <summary>
                    지도 변경안 자세히 보기
                    <span>
                      노드 {{ messageJob(item)?.proposal?.nodes.length }},
                      연결 {{ messageJob(item)?.proposal?.edges.length }},
                      조건 {{ messageJob(item)?.proposal?.requirements.length }}
                    </span>
                    <ChevronDown :size="17" />
                  </summary>
                  <div class="proposal-section">
                    <h4>역량과 기회</h4>
                    <article
                      v-for="node in messageJob(item)?.proposal?.nodes ?? []"
                      :key="node.ref"
                      class="proposal-row"
                    >
                      <span :class="`proposal-action proposal-action--${node.action.toLowerCase()}`">
                        {{ node.action === "CREATE" ? "새로 추가" : "기존 연결" }}
                      </span>
                      <div>
                        <strong>{{ node.title }}</strong>
                        <p>{{ node.scopeDefinition ?? "기존 지도에 정의된 범위를 재사용합니다." }}</p>
                        <small>{{ node.domain }} · {{ node.kind }} · 수준 {{ node.level }}</small>
                      </div>
                    </article>
                  </div>
                  <div class="proposal-section">
                    <h4>공고 조건</h4>
                    <article
                      v-for="requirement in messageJob(item)?.proposal?.requirements ?? []"
                      :key="`${requirement.nodeRef}-${requirement.kind}`"
                      class="proposal-row"
                    >
                      <span :class="`requirement-pill requirement-pill--${requirement.kind.toLowerCase()}`">
                        {{ requirement.kind === "REQUIRED" ? "필수" : "우대" }}
                      </span>
                      <div>
                        <strong>{{ requirement.sourceText ?? "공고의 관련 조건" }}</strong>
                        <small v-if="requirement.confidence !== null">
                          분석 신뢰도 {{ Math.round(requirement.confidence * 100) }}%
                        </small>
                      </div>
                    </article>
                  </div>
                </details>

                <div
                  v-if="messageJob(item)?.changeSetStatus === 'PROPOSED'"
                  class="analysis-actions"
                >
                  <button
                    class="press-button press-button--ghost"
                    type="button"
                    :disabled="actionJobId === item.analysisJobId"
                    @click="reject(messageJob(item)!)"
                  >
                    <X :size="17" />
                    반영하지 않기
                  </button>
                  <button
                    class="press-button press-button--primary"
                    type="button"
                    :disabled="actionJobId === item.analysisJobId"
                    @click="approve(messageJob(item)!)"
                  >
                    <Check :size="18" />
                    검토했고 지도에 반영
                    <ArrowRight :size="17" />
                  </button>
                </div>
                <div
                  v-else-if="messageJob(item)?.changeSetStatus === 'APPROVED'"
                  class="analysis-resolution analysis-resolution--applied"
                >
                  <Check :size="17" />
                  커리어 지도에 반영되었습니다.
                </div>
                <div
                  v-else-if="messageJob(item)?.changeSetStatus === 'REJECTED'"
                  class="analysis-resolution"
                >
                  이 변경안은 반영하지 않았습니다.
                </div>
              </template>
            </section>

            <section
              v-if="
                item.role === 'USER' &&
                chatJobForMessage(item) &&
                chatJobForMessage(item)?.status !== 'SUCCEEDED'
              "
              class="inline-ai-status"
              :class="`inline-ai-status--${chatJobForMessage(item)?.status.toLowerCase()}`"
            >
              <template
                v-if="['QUEUED', 'RUNNING'].includes(chatJobForMessage(item)?.status ?? '')"
              >
                <LoaderCircle class="spin" :size="17" />
                <span>{{ chatJobForMessage(item)?.stageMessage }}</span>
              </template>
              <template v-else-if="chatJobForMessage(item)?.status === 'FAILED'">
                <CircleAlert :size="17" />
                <span>
                  {{ chatJobForMessage(item)?.errorMessage ?? "AI 답변을 만들지 못했어요." }}
                </span>
                <button
                  v-if="(chatJobForMessage(item)?.attemptCount ?? 3) < 3"
                  class="text-action"
                  type="button"
                  :disabled="actionJobId === chatJobForMessage(item)?.id"
                  @click="retryChat(chatJobForMessage(item)!)"
                >
                  <RefreshCw :size="13" /> 다시 답변
                </button>
              </template>
            </section>
          </div>
        </article>
      </div>

      <footer class="chat-composer">
        <p v-if="error" class="form-error">{{ error }}</p>
        <div class="composer-box">
          <button
            class="composer-attach"
            type="button"
            aria-label="공고 첨부"
            title="공고 첨부"
            @click="showPosting = true"
          >
            <Paperclip :size="20" />
          </button>
          <textarea
            v-model="message"
            rows="1"
            maxlength="4000"
            placeholder="커리어에 관해 자유롭게 물어보세요. 공고는 왼쪽 첨부 버튼으로 추가할 수 있어요."
            @keydown="onComposerKeydown"
          />
          <button
            class="composer-send"
            type="button"
            :disabled="!message.trim() || sending"
            aria-label="메시지 보내기"
            @click="sendText"
          >
            <LoaderCircle v-if="sending" class="spin" :size="20" />
            <Send v-else :size="20" />
          </button>
        </div>
        <small>Enter로 전송 · Shift+Enter로 줄바꿈</small>
      </footer>
    </section>

    <button
      v-if="showPosting"
      class="modal-backdrop"
      type="button"
      aria-label="공고 첨부 닫기"
      @click="showPosting = false"
    />
    <section v-if="showPosting" class="posting-modal" role="dialog" aria-modal="true">
      <header>
        <div class="modal-icon"><BriefcaseBusiness :size="22" /></div>
        <div>
          <p class="eyebrow">ATTACH A POSTING</p>
          <h2>분석할 채용 공고</h2>
        </div>
        <button class="icon-button" type="button" @click="showPosting = false">
          <X :size="20" />
        </button>
      </header>
      <div class="source-tabs">
        <button
          type="button"
          :class="{ active: sourceType === 'TEXT' }"
          @click="sourceType = 'TEXT'"
        >
          공고문 붙여넣기
        </button>
        <button
          type="button"
          :class="{ active: sourceType === 'URL' }"
          @click="sourceType = 'URL'"
        >
          URL과 본문
        </button>
      </div>
      <label v-if="sourceType === 'URL'">
        공고 URL
        <input v-model="sourceUrl" type="url" required placeholder="https://…" />
      </label>
      <label>
        공고 원문
        <textarea
          v-model="rawText"
          minlength="20"
          maxlength="100000"
          placeholder="회사, 직무, 자격 요건, 우대 사항을 포함한 공고 원문을 붙여넣어 주세요."
        />
        <small>{{ rawText.length.toLocaleString() }} / 100,000자</small>
      </label>
      <button
        class="press-button press-button--primary modal-submit"
        type="button"
        :disabled="rawText.trim().length < 20 || sending"
        @click="attachPosting"
      >
        <LoaderCircle v-if="sending" class="spin" :size="19" />
        <FilePlus2 v-else :size="19" />
        저장하고 분석 시작
      </button>
    </section>
  </main>
</template>
