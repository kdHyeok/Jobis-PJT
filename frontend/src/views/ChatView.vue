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
  Sparkles,
  Trash2,
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
const showNewMessages = ref(false);
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

function roadmapCompetenciesFor(item: ConversationMessage) {
  return (messageJob(item)?.proposal?.competencies ?? []).filter(
    (competency) => competency.roadmapEligible !== false,
  );
}

function qualitativeCompetenciesFor(item: ConversationMessage) {
  return (messageJob(item)?.proposal?.competencies ?? []).filter(
    (competency) => competency.roadmapEligible === false,
  );
}

function chatJobForMessage(item: ConversationMessage): ChatReplyJob | null {
  return (
    Object.values(chatJobsById.value).find(
      (job) => job.triggerMessageId === item.id,
    ) ?? null
  );
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

function isNearMessageBottom(threshold = 120) {
  const list = messageList.value;
  if (!list) return true;
  return list.scrollHeight - list.scrollTop - list.clientHeight <= threshold;
}

function onMessageListScroll() {
  if (isNearMessageBottom()) showNewMessages.value = false;
}

function messageUpdateSignature() {
  const messages = (conversation.value?.messages ?? [])
    .map((item) => `${item.id}:${item.content.length}`)
    .join("|");
  const analyses = Object.values(analysisById.value)
    .map((item) => {
      const lastEvent = item.progressEvents[item.progressEvents.length - 1];
      const lastSequence = lastEvent?.sequence ?? 0;
      return `${item.id}:${item.status}:${item.stage}:${lastSequence}`;
    })
    .sort()
    .join("|");
  const replies = Object.values(chatJobsById.value)
    .map((item) => `${item.id}:${item.status}:${item.stage}`)
    .sort()
    .join("|");
  return `${messages}::${analyses}::${replies}`;
}

async function scrollToBottom(behavior: ScrollBehavior = "smooth") {
  await nextTick();
  const list = messageList.value;
  if (!list) return;
  list.scrollTo({
    top: list.scrollHeight,
    behavior,
  });
  showNewMessages.value = false;
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
  await scrollToBottom("auto");
}

async function refreshConversationList() {
  conversations.value = await api.conversations();
}

async function openConversation(id: string) {
  conversation.value = await api.conversation(id);
  await hydrateJobs();
  await scrollToBottom("auto");
}

async function deleteConversation(id: string) {
  if (!window.confirm("이 대화 세션을 삭제할까요? 연결된 공고와 분석 기록은 유지됩니다.")) {
    return;
  }
  error.value = "";
  try {
    await api.deleteConversation(id);
    const next = conversations.value.find((item) => item.id !== id)?.id;
    conversation.value = null;
    await loadConversations(next);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "대화를 삭제하지 못했습니다.";
  }
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
  const followLatest = isNearMessageBottom();
  const previousSignature = messageUpdateSignature();
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
  const contentChanged = previousSignature !== messageUpdateSignature();
  if (contentChanged) {
    if (followLatest) await scrollToBottom();
    else showNewMessages.value = true;
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
    error.value = cause instanceof Error ? cause.message : "목표 공고에 추가하지 못했습니다.";
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
      <div
        v-for="item in conversations"
        :key="item.id"
        class="conversation-link-row"
      >
        <button
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
        <button
          class="conversation-delete"
          type="button"
          :aria-label="`${item.title} 삭제`"
          title="대화 삭제"
          @click="deleteConversation(item.id)"
        >
          <Trash2 :size="15" />
        </button>
      </div>
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

      <div
        ref="messageList"
        class="message-list"
        aria-live="polite"
        @scroll.passive="onMessageListScroll"
      >
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
            <Sparkles :size="18" />
          </div>
          <div class="chat-bubble">
            <p>{{ item.content }}</p>
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
                    :queue-position="messageJob(item)?.queuePosition"
                    :events="messageJob(item)?.progressEvents"
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
                    :queue-position="messageJob(item)?.queuePosition"
                    :events="messageJob(item)?.progressEvents"
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
                  <details
                    v-if="messageJob(item)?.questionHistory?.length"
                    class="analysis-question-history"
                  >
                    <summary>
                      이전 확인 답변 {{ messageJob(item)?.questionHistory?.length ?? 0 }}개
                    </summary>
                    <ol>
                      <li
                        v-for="history in messageJob(item)?.questionHistory ?? []"
                        :key="history.id"
                      >
                        <strong>{{ history.text }}</strong>
                        <span>{{ history.answerValue }}</span>
                      </li>
                    </ol>
                  </details>
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
                    분석된 역량 자세히 보기
                    <span>
                      역량 {{ messageJob(item)?.proposal?.competencies.length }},
                      조건 {{ messageJob(item)?.proposal?.requirements.length }}
                    </span>
                    <ChevronDown :size="17" />
                  </summary>
                  <div class="proposal-section">
                    <h4>로드맵 제작에 사용할 역량</h4>
                    <article
                      v-for="competency in roadmapCompetenciesFor(item)"
                      :key="competency.ref"
                      class="proposal-row"
                    >
                      <span class="proposal-action proposal-action--create">
                        {{ competency.stage }}
                      </span>
                      <div>
                        <strong>{{ competency.title }}</strong>
                        <p>{{ competency.scopeDefinition }}</p>
                        <small>
                          {{ competency.domain }} · {{ competency.kind }} · 요구 수준
                          {{ competency.requiredLevel }}
                        </small>
                        <small v-if="competency.verificationMethod">
                          검증: {{ competency.verificationMethod }}
                        </small>
                      </div>
                    </article>
                  </div>
                  <div
                    v-if="qualitativeCompetenciesFor(item).length"
                    class="proposal-section proposal-section--qualitative"
                  >
                    <h4>정성적 채용 조건</h4>
                    <p>
                      로드맵과 준비도 계산에는 포함하지 않는 참고 조건입니다.
                    </p>
                    <article
                      v-for="competency in qualitativeCompetenciesFor(item)"
                      :key="competency.ref"
                      class="proposal-row"
                    >
                      <span class="proposal-action">참고</span>
                      <div>
                        <strong>{{ competency.title }}</strong>
                        <p>{{ competency.scopeDefinition }}</p>
                      </div>
                    </article>
                  </div>
                  <div class="proposal-section">
                    <h4>공고 조건</h4>
                    <article
                      v-for="requirement in messageJob(item)?.proposal?.requirements ?? []"
                      :key="`${requirement.competencyRef}-${requirement.relation}`"
                      class="proposal-row"
                    >
                      <span
                        :class="`requirement-pill requirement-pill--${requirement.relation.toLowerCase()}`"
                      >
                        {{
                          requirement.relation === "REQUIRED"
                            ? "필수"
                            : requirement.relation === "PREFERRED"
                              ? "우대"
                              : "업무"
                        }}
                      </span>
                      <div>
                        <strong>{{ requirement.sourceText }}</strong>
                        <small>
                          분석 신뢰도 {{ Math.round(requirement.confidence * 100) }}%
                        </small>
                      </div>
                    </article>
                  </div>
                  <div
                    v-if="messageJob(item)?.proposal?.targetProject"
                    class="proposal-section"
                  >
                    <h4>회사 맞춤 프로젝트</h4>
                    <article class="proposal-row">
                      <span class="proposal-action proposal-action--create">PROJECT</span>
                      <div>
                        <strong>{{ messageJob(item)?.proposal?.targetProject.title }}</strong>
                        <p>{{ messageJob(item)?.proposal?.targetProject.objective }}</p>
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
                    :disabled="
                      actionJobId === item.analysisJobId ||
                      ['EXPIRED', 'CLOSED'].includes(
                        messageJob(item)?.result?.job?.lifecycleStatus ?? '',
                      )
                    "
                    @click="approve(messageJob(item)!)"
                  >
                    <Check :size="18" />
                    목표 공고에 추가
                    <ArrowRight :size="17" />
                  </button>
                </div>
                <div
                  v-else-if="messageJob(item)?.changeSetStatus === 'APPROVED'"
                  class="analysis-resolution analysis-resolution--applied"
                >
                  <Check :size="17" />
                  목표 목록에 추가되었습니다. 로드맵에서 새 초안을 적용해 주세요.
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

      <button
        v-if="showNewMessages"
        class="chat-new-message"
        type="button"
        @click="scrollToBottom()"
      >
        새 메시지
        <ChevronDown :size="16" :stroke-width="3" />
      </button>

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
