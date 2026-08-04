<script setup lang="ts">
import {
  ArrowRight,
  BriefcaseBusiness,
  Check,
  ChevronDown,
  CircleAlert,
  CircleHelp,
  FilePlus2,
  FileUp,
  LoaderCircle,
  MessageCircleMore,
  Paperclip,
  Plus,
  RefreshCw,
  Send,
  Sparkles,
  Trash2,
  Upload,
  X,
} from "@lucide/vue";
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { agentIdentity } from "@/agents";
import { api } from "@/api";
import AnalysisProgressWheel from "@/components/AnalysisProgressWheel.vue";
import {
  RESUME_ACCEPT,
  RESUME_MIN_CHARS,
  readResumeFile,
  titleFromFileName,
} from "@/resumeFile";
import type {
  AnalysisJob,
  ChatAgentStep,
  ChatReplyJob,
  ChatReplyMetadata,
  ChatReplySource,
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
// 첨부는 한 자리에서 받는다 — 버튼 두 개(공고·이력서)가 따로 있으면 무엇을 올리는
// 자리인지 아이콘만 보고는 알 수 없었다. 팝업 안에서 대상을 먼저 고른다.
const showPosting = ref(false);
const attachKind = ref<"POSTING" | "RESUME">("POSTING");
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

/**
 * 진행 단계 목록 → 에이전트별 말풍선.
 *
 * 이어지는 같은 화자의 단계는 한 말풍선으로 묶는다 — 도구를 세 번 부른 담당이 말풍선 세
 * 개로 갈리면 대화가 아니라 로그로 읽힌다. 색·로고는 `agent` 키로만 고른다.
 */
type AgentTurn = {
  key: string;
  agent: string;
  identity: ReturnType<typeof agentIdentity>;
  lines: string[];
  /** 담당이 완성한 발화 본문(D153) — 과정 라벨(lines)과 달리 대화 내용으로 그린다. */
  speech: string[];
  running: boolean;
};

function agentTurns(steps: ChatAgentStep[] | null | undefined): AgentTurn[] {
  const turns: AgentTurn[] = [];
  (steps ?? []).forEach((step, index) => {
    const identity = agentIdentity(step.agent);
    // 화자 이름과 다른 라벨(예: "계획 수립", "자소서 초안 루프")만 문구 앞에 붙인다.
    const line = [step.label === identity.label ? "" : step.label, step.detail]
      .filter((part) => part && part.trim())
      .join(" · ");
    const spoken = (step.message ?? "").trim();
    if (!line && !spoken) return;
    const last = turns[turns.length - 1];
    if (last && last.agent === step.agent) {
      if (line) last.lines.push(line);
      if (spoken) last.speech.push(spoken);
      last.running = step.step.startsWith("start:");
      return;
    }
    turns.push({
      key: `${index}-${step.agent}`,
      agent: step.agent,
      identity,
      lines: line ? [line] : [],
      speech: spoken ? [spoken] : [],
      // "실행 중…"(start:*)으로 끝난 담당이 지금 일하는 담당이다.
      running: step.step.startsWith("start:"),
    });
  });
  return turns;
}

function chatTurnsFor(item: ConversationMessage): AgentTurn[] {
  return agentTurns(chatJobForMessage(item)?.progressSteps);
}

/**
 * 최종 답변의 화자별 조각. AI 가 `replySources` 를 준 턴은 담당별로 말풍선을 나눈다 —
 * 여러 담당이 만든 답변을 한 덩어리로 붙이면 누가 무엇을 말했는지 사라진다.
 * 없으면(구버전 응답·단일 담당) 빈 배열이고 화면은 기존 한 덩어리 말풍선을 쓴다.
 */
function replyMetadata(item: ConversationMessage): ChatReplyMetadata {
  return (item.metadata ?? {}) as ChatReplyMetadata;
}

function replySourcesFor(item: ConversationMessage): ChatReplySource[] {
  const sources = replyMetadata(item).replySources;
  if (!Array.isArray(sources)) return [];
  const spoken = sources.filter((source) => (source.text ?? "").trim());
  return spoken.length > 1 ? spoken : [];
}

/** 이 답변이 LLM 실패 뒤의 결정론 요약본이면 그 이유. 정상 답변이면 빈 문자열. */
function degradedReasonFor(item: ConversationMessage): string {
  return (replyMetadata(item).degradedReason ?? "").trim();
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
    // 단계 수까지 본다 — 상태·stage 가 같아도 새 담당이 말하면 화면이 자라기 때문이다.
    .map(
      (item) =>
        `${item.id}:${item.status}:${item.stage}:${item.progressSteps?.length ?? 0}`,
    )
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

// 공고를 붙일 수 있는 조건 — **버튼과 함수가 같은 규칙을 본다.**
// 전에는 버튼의 :disabled 와 함수의 가드가 따로 있어서, 하나만 고치면 다른 쪽이 막았다.
// URL 만 주는 것이 정상 입력이다: 원문은 AI 가 주소에서 수집한다(posting_fetch).
//
// **기준값은 지어내지 않고 AI 가 실제로 받아들이는 값을 쓴다.**
// - 본문 최소 40자: `AI/src/jobis_ai/orchestrator/attachment_kind.py` MIN_ASSET_CHARS
//   (이보다 짧으면 AI 가 자산으로 승격하지 않는다 — UI 만 통과시키면 조용히 무시된다)
// - URL 판별: 같은 저장소가 쓰는 `startswith("http://" | "https://")` 와 동일하게 둔다
const POSTING_MIN_CHARS = 40;
const postingUrlValid = computed(() => {
  const url = sourceUrl.value.trim();
  return (url.startsWith("http://") || url.startsWith("https://")) && url.length > 8;
});
const postingBodyValid = computed(
  () => rawText.value.trim().length >= POSTING_MIN_CHARS,
);
const canAttachPosting = computed(() =>
  sourceType.value === "URL"
    ? postingUrlValid.value || postingBodyValid.value
    : postingBodyValid.value,
);

async function attachPosting() {
  if (!conversation.value) return;
  if (!canAttachPosting.value) {
    error.value =
      sourceType.value === "URL"
        ? `공고 주소를 http(s):// 로 시작하게 입력하거나, 원문을 ${POSTING_MIN_CHARS}자 이상 붙여넣어 주세요.`
        : `공고 원문을 ${POSTING_MIN_CHARS}자 이상 붙여넣어 주세요.`;
    return;
  }
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
    // 첨부도 대화다 — 에이전트 답변 작업을 일반 발화와 똑같이 따라간다. 이게 없으면 답변이
    // 만들어져도 화면이 폴링하지 않아 새로고침 전까지 안 보인다.
    if (result.chatReplyJobId) {
      chatJobsById.value[result.chatReplyJobId] = await api.chatReplyJob(
        result.chatReplyJobId,
      );
      schedulePoll();
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

// 이력서 첨부 — 대화 중에 들어오는 이력서를 공고와 같은 자리에서 받는다.
// 등록은 커리어 저장소로 간다(파편 확정은 저장소 화면에서 사용자가 한다 — 여기서 자동
// 확정하지 않는다). docx 는 서버가 푼다(`resumeFile.readResumeFile`).
const uploadingResume = ref(false);
const notice = ref("");
const resumeText = ref("");
const resumeFileName = ref("");
const resumeBase64 = ref("");

const canAttachResume = computed(
  () => Boolean(resumeBase64.value) || resumeText.value.trim().length >= RESUME_MIN_CHARS,
);

async function readResume(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  error.value = "";
  try {
    const payload = await readResumeFile(file);
    resumeFileName.value = payload.fileName;
    resumeBase64.value = payload.fileBase64 ?? "";
    resumeText.value = payload.rawText;
  } catch (cause) {
    error.value =
      cause instanceof Error ? cause.message : "이력서 파일을 읽지 못했습니다.";
  } finally {
    input.value = "";
  }
}

async function attachResume() {
  if (!canAttachResume.value) {
    error.value = `이력서 파일을 고르거나 원문을 ${RESUME_MIN_CHARS}자 이상 붙여넣어 주세요.`;
    return;
  }
  uploadingResume.value = true;
  error.value = "";
  notice.value = "";
  const label = resumeFileName.value || "대화에서 붙여넣은 이력서";
  try {
    await api.createCareerSource({
      sourceType: resumeFileName.value ? "FILE" : "TEXT",
      title: titleFromFileName(label),
      sourceUrl: null,
      rawText: resumeText.value.trim(),
      ...(resumeBase64.value
        ? { fileBase64: resumeBase64.value, fileName: resumeFileName.value }
        : {}),
    });
    // 추출은 비동기다(CareerExtractionWorker) — 끝난 척하지 않고 어디서 확인하는지 알린다.
    // 성공은 `error` 가 아니라 `notice` 로 낸다(빨간 글씨로 성공을 알리지 않는다).
    notice.value = `'${label}'을 커리어 저장소에 등록했어요. 읽고 나면 저장소에서 저장할 조각을 고를 수 있어요.`;
    showPosting.value = false;
    resumeText.value = "";
    resumeFileName.value = "";
    resumeBase64.value = "";
  } catch (cause) {
    error.value =
      cause instanceof Error ? cause.message : "이력서를 등록하지 못했습니다.";
  } finally {
    uploadingResume.value = false;
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
            <!--
              여러 담당이 만든 답변은 담당별로 나눠 말한다(replySources). 한 담당이거나
              화자 정보가 없는 턴은 그대로 한 덩어리다 — 없는 화자를 지어내지 않는다.
            -->
            <template v-if="replySourcesFor(item).length">
              <article
                v-for="(source, index) in replySourcesFor(item)"
                :key="index"
                class="agent-reply"
                :style="{ '--agent-color': agentIdentity(source.agent).color }"
              >
                <span class="agent-reply__avatar">
                  <component
                    :is="agentIdentity(source.agent).icon"
                    :size="16"
                    stroke-width="2.6"
                  />
                </span>
                <div>
                  <strong>{{ agentIdentity(source.agent).label }}</strong>
                  <p>{{ source.text }}</p>
                </div>
              </article>
            </template>
            <!--
              내용이 빈 메시지는 문장 자리를 만들지 않는다. 진행 휠이 붙는 상태 메시지
              (ANALYSIS_STATUS)는 **사용자향 문장을 담지 않는다** — 그 말은 에이전트가 한다.
              막지 않으면 아바타만 있는 빈 말풍선이 뜬다.
            -->
            <p v-else-if="item.content.trim()">{{ item.content }}</p>

            <!--
              폴백 답변임을 답변 옆에서 알린다. 로그에만 남기면 답변을 읽는 사람은
              요약본을 분석 결과로 읽는다 — 두 번 그렇게 됐다.
            -->
            <p v-if="degradedReasonFor(item)" class="reply-degraded">
              <CircleAlert :size="15" />
              <span>{{ degradedReasonFor(item) }}</span>
            </p>
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

            <!--
              어느 담당이 지금 무엇을 하는지 — 에이전트마다 색·로고가 다른 말풍선으로
              순서대로 말한다. 끝난 턴은 접어 둔다(기록은 남기되 대화를 가리지 않게).
            -->
            <component
              :is="chatJobForMessage(item)?.status === 'SUCCEEDED' ? 'details' : 'div'"
              v-if="item.role === 'USER' && chatTurnsFor(item).length"
              class="agent-stream"
            >
              <summary v-if="chatJobForMessage(item)?.status === 'SUCCEEDED'">
                담당 {{ chatTurnsFor(item).length }}명이 처리한 과정 보기
                <ChevronDown :size="15" />
              </summary>
              <article
                v-for="turn in chatTurnsFor(item)"
                :key="turn.key"
                class="agent-turn"
                :class="{ 'agent-turn--running': turn.running }"
                :style="{ '--agent-color': turn.identity.color }"
              >
                <span class="agent-turn__avatar">
                  <component :is="turn.identity.icon" :size="17" stroke-width="2.6" />
                </span>
                <div class="agent-turn__bubble">
                  <strong>
                    {{ turn.identity.label }}
                    <LoaderCircle v-if="turn.running" class="spin" :size="12" />
                  </strong>
                  <p v-for="(line, index) in turn.lines" :key="index">{{ line }}</p>
                  <!-- 담당이 말을 마치는 즉시 발화 본문을 그대로 보여준다(D153) —
                       과정 라벨과 달리 이건 대화 내용이다. 끝난 턴의 최종 답변
                       (replySources)과 같은 내용이지만, 그때는 이 영역이 접힌다. -->
                  <p
                    v-for="(spoken, index) in turn.speech"
                    :key="`speech-${index}`"
                    class="agent-turn__speech"
                  >
                    {{ spoken }}
                  </p>
                </div>
              </article>
            </component>

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
        <p v-else-if="notice" class="composer-notice">{{ notice }}</p>
        <div class="composer-box">
          <button
            class="composer-attach"
            type="button"
            aria-label="공고·이력서 첨부"
            title="공고·이력서 첨부"
            @click="showPosting = true"
          >
            <LoaderCircle v-if="uploadingResume" class="spin" :size="20" />
            <Paperclip v-else :size="20" />
          </button>
          <textarea
            v-model="message"
            rows="1"
            maxlength="4000"
            placeholder="커리어에 관해 자유롭게 물어보세요. 공고와 이력서는 왼쪽 클립 버튼으로 추가할 수 있어요."
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
          <p class="eyebrow">ATTACH</p>
          <h2>무엇을 분석할까요?</h2>
        </div>
        <button class="icon-button" type="button" @click="showPosting = false">
          <X :size="20" />
        </button>
      </header>
      <div class="source-tabs">
        <button
          type="button"
          :class="{ active: attachKind === 'POSTING' }"
          @click="attachKind = 'POSTING'"
        >
          분석할 채용 공고
        </button>
        <button
          type="button"
          :class="{ active: attachKind === 'RESUME' }"
          @click="attachKind = 'RESUME'"
        >
          분석할 이력서
        </button>
      </div>

      <template v-if="attachKind === 'POSTING'">
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
            공고 URL
          </button>
        </div>
        <label v-if="sourceType === 'URL'">
          공고 URL
          <input v-model="sourceUrl" type="url" required placeholder="https://…" />
        </label>
        <label>
          공고 원문<span v-if="sourceType === 'URL'"> (선택 — 비우면 주소에서 수집합니다)</span>
          <textarea
            v-model="rawText"
            :minlength="POSTING_MIN_CHARS"
            maxlength="100000"
            :placeholder="
              sourceType === 'URL'
                ? '주소만 넣어도 됩니다. 원문이 있으면 붙여넣어 주세요.'
                : '회사, 직무, 자격 요건, 우대 사항을 포함한 공고 원문을 붙여넣어 주세요.'
            "
          />
          <small>{{ rawText.length.toLocaleString() }} / 100,000자</small>
        </label>
        <button
          class="press-button press-button--primary modal-submit"
          type="button"
          :disabled="!canAttachPosting || sending"
          @click="attachPosting"
        >
          <LoaderCircle v-if="sending" class="spin" :size="19" />
          <FilePlus2 v-else :size="19" />
          저장하고 분석 시작
        </button>
      </template>

      <template v-else>
        <label class="file-drop">
          <Upload :size="22" />
          <strong>{{ resumeFileName || "이력서 파일 올리기" }}</strong>
          <span>DOCX, TXT, MD · 최대 2MB</span>
          <input
            type="file"
            :accept="RESUME_ACCEPT"
            :disabled="uploadingResume"
            @change="readResume"
          />
        </label>
        <label>
          이력서 원문
          <textarea
            v-model="resumeText"
            :minlength="RESUME_MIN_CHARS"
            maxlength="100000"
            :placeholder="
              resumeBase64
                ? 'docx 원문은 등록할 때 서버가 읽습니다 — 비워 두어도 됩니다.'
                : '이력서, 경력기술서, 프로젝트에서 맡은 역할과 결과를 붙여넣어 주세요.'
            "
          />
          <small>{{ resumeText.length.toLocaleString() }} / 100,000자</small>
        </label>
        <p class="form-hint">
          커리어 저장소에 등록됩니다. AI가 읽고 나면 저장할 조각을 직접 고릅니다.
        </p>
        <button
          class="press-button press-button--primary modal-submit"
          type="button"
          :disabled="!canAttachResume || uploadingResume"
          @click="attachResume"
        >
          <LoaderCircle v-if="uploadingResume" class="spin" :size="19" />
          <FileUp v-else :size="19" />
          커리어 저장소에 등록
        </button>
      </template>
    </section>
  </main>
</template>
