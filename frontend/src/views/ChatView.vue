<script setup lang="ts">
import {
  ArrowRight,
  BriefcaseBusiness,
  Archive,
  ArchiveRestore,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  CircleHelp,
  CircleX,
  FilePlus2,
  Globe2,
  LoaderCircle,
  MessageCircleMore,
  Paperclip,
  Pencil,
  RefreshCw,
  RotateCcw,
  Send,
  Sparkles,
  Trash2,
  X,
} from "@lucide/vue";
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api } from "@/api";
import { hasUnreadCompletedReply, markConversationSeen } from "@/conversation-read-state";
import { learningChats } from "@/learning-plan";
import { productDialog } from "@/product-dialog";
import AgentExecutionMap from "@/components/AgentExecutionMap.vue";
import AgentWorkProductCard from "@/components/AgentWorkProductCard.vue";
import AgentMessageContent from "@/components/AgentMessageContent.vue";
import AnalysisProgressWheel from "@/components/AnalysisProgressWheel.vue";
import V3PostingReviewCard from "@/components/V3PostingReviewCard.vue";
import type {
  AgentArtifact,
  AgentActionExecution,
  AgentProposedAction,
  AgentChatResult,
  AgentContext,
  AgentMode,
  AgentProgressEvent,
  AnalysisJob,
  CareerSourceSummary,
  ChatReplyJob,
  Conversation,
  ConversationMessage,
  ConversationSummary,
  Posting,
  V3SourceView,
} from "@/types";

const route = useRoute();
const router = useRouter();
const conversations = ref<ConversationSummary[]>([]);
const conversationQuery = ref("");
const conversationStatus = ref<"ACTIVE" | "LEARNING">("ACTIVE");
const conversationPage = ref(0);
const conversationTotal = ref(0);
const loadingOlderMessages = ref(false);
const conversation = ref<Conversation | null>(null);
const message = ref("");
const loading = ref(true);
const sending = ref(false);
const error = ref("");
const showPosting = ref(false);
const sourceType = ref<"TEXT" | "URL">("TEXT");
const sourceUrl = ref("");
const rawText = ref("");
const attachedV3Source = ref<V3SourceView | null>(null);
const attachedExtractedText = ref("");
const attachedPostingReviewState = ref<"NONE" | "PENDING" | "READY">("NONE");
const analysisById = ref<Record<string, AnalysisJob>>({});
const answerSelections = ref<Record<string, string>>({});
const chatJobsById = ref<Record<string, ChatReplyJob>>({});
const actionJobId = ref<string | null>(null);
const messageList = ref<HTMLElement | null>(null);
const composerInput = ref<HTMLTextAreaElement | null>(null);
const resumeFileInput = ref<HTMLInputElement | null>(null);
const showNewMessages = ref(false);
const showAgentContext = ref(false);
const agentMode = ref<AgentMode>("AUTO");
const availablePostings = ref<Posting[]>([]);
const availableCareerSources = ref<CareerSourceSummary[]>([]);
const selectedPostingIds = ref<string[]>([]);
const selectedCareerSourceIds = ref<string[]>([]);
const assetsLoading = ref(false);
let pollTimer: number | null = null;
let conversationRequestSequence = 0;
const forcedAnalysisPollIds = ref<Set<string>>(new Set());
const forcedAnalysisPollDeadlines = new Map<string, number>();
const activePostingReviewKey = ref<string | null>(null);
const postingReviewEdits = ref<Record<string, string>>({});
const CHAT_POSTING_DRAFT_KEY = "jobis:v3-chat-posting-draft";
const CHAT_COMPOSER_DRAFT_PREFIX = "jobis:chat-composer:";
const HANDLED_POSTING_REVIEW_KEY = "jobis:v3-handled-posting-reviews";
const CHAT_INPUT_MAX_CHARS = 20_000;
const POSTING_ANALYSIS_SUFFIX = "\n\n위 채용 공고를 분석해줘";
const POSTING_URL_ANALYSIS_SUFFIX = "\n\n이 채용 공고를 분석해줘";
const POSTING_TEXT_MAX_CHARS = CHAT_INPUT_MAX_CHARS - POSTING_ANALYSIS_SUFFIX.length;

const composerContent = computed(() => message.value.trim());
const composerHint = computed(() => {
  const content = composerContent.value;
  if (!content) {
    return "Enter로 전송 · JOBIS가 대화 맥락을 보고 필요한 작업을 선택해요";
  }
  return `${content.length.toLocaleString()} / ${CHAT_INPUT_MAX_CHARS.toLocaleString()}자 · Shift+Enter로 줄바꿈`;
});
const composerHasLengthError = computed(
  () => composerContent.value.length > CHAT_INPUT_MAX_CHARS,
);

watch([
  sourceType,
  sourceUrl,
  rawText,
  attachedV3Source,
  attachedExtractedText,
  attachedPostingReviewState,
  activePostingReviewKey,
], () => {
  if (!conversation.value) return;
  if (!sourceUrl.value && !rawText.value && !attachedV3Source.value) {
    window.localStorage.removeItem(CHAT_POSTING_DRAFT_KEY);
    return;
  }
  window.localStorage.setItem(CHAT_POSTING_DRAFT_KEY, JSON.stringify({
    conversationId: conversation.value.id,
    sourceType: sourceType.value,
    sourceUrl: sourceUrl.value,
    rawText: rawText.value,
    sourceId: attachedV3Source.value?.id ?? null,
    extractedText: attachedExtractedText.value || null,
    reviewState: attachedPostingReviewState.value,
    reviewKey: activePostingReviewKey.value,
  }));
});

const agentModes: Array<{
  value: AgentMode;
  label: string;
  description: string;
  postingMinimum: number;
  sourceMinimum: number;
}> = [
  {
    value: "AUTO",
    label: "자동 선택",
    description: "대화와 보유 자료를 보고 JOBIS가 필요한 에이전트를 자동으로 선택합니다.",
    postingMinimum: 0,
    sourceMinimum: 0,
  },
  {
    value: "CAREER_CHAT",
    label: "자유 대화",
    description: "목표, 경험, 학습 방향을 자유롭게 이야기합니다.",
    postingMinimum: 0,
    sourceMinimum: 0,
  },
  {
    value: "POSTING_QA",
    label: "공고 질문",
    description: "선택한 공고의 조건과 의미를 근거로 설명합니다.",
    postingMinimum: 1,
    sourceMinimum: 0,
  },
  {
    value: "RESUME_DIAGNOSIS",
    label: "이력서 진단",
    description: "선택한 커리어 자료의 강점과 공백을 진단합니다.",
    postingMinimum: 0,
    sourceMinimum: 1,
  },
  {
    value: "POSTING_COMPARE",
    label: "공고 비교",
    description: "둘 이상의 공고를 같은 기준으로 비교합니다.",
    postingMinimum: 2,
    sourceMinimum: 0,
  },
  {
    value: "RESUME_COMPARE",
    label: "이력서 비교",
    description: "둘 이상의 커리어 자료를 비교해 사용할 버전을 찾습니다.",
    postingMinimum: 0,
    sourceMinimum: 2,
  },
  {
    value: "INTERVIEW_PREP",
    label: "면접 준비",
    description: "공고와 내 경험에 맞춘 질문과 평가 기준을 만듭니다.",
    postingMinimum: 1,
    sourceMinimum: 0,
  },
  {
    value: "COVER_LETTER",
    label: "자소서 초안",
    description: "공고와 확인된 커리어 근거로 회사 맞춤 초안을 만듭니다.",
    postingMinimum: 1,
    sourceMinimum: 1,
  },
  {
    value: "APPLICATION_PLAN",
    label: "지원 계획",
    description: "필수 조건과 마감에 맞춘 준비 순서를 정합니다.",
    postingMinimum: 1,
    sourceMinimum: 0,
  },
  {
    value: "JOB_DISCOVERY",
    label: "공고 탐색",
    description: "희망 조건을 정리해 실제 공고 탐색 기준을 만듭니다.",
    postingMinimum: 0,
    sourceMinimum: 0,
  },
];

const selectedMode = computed(
  () => agentModes.find((item) => item.value === agentMode.value) ?? agentModes[0],
);

const contextReady = computed(
  () =>
    selectedPostingIds.value.length >= selectedMode.value.postingMinimum &&
    selectedCareerSourceIds.value.length >= selectedMode.value.sourceMinimum,
);

const currentAgentContext = computed<AgentContext>(() => ({
  mode: agentMode.value,
  postingIds: selectedPostingIds.value,
  careerSourceIds: selectedCareerSourceIds.value,
}));

const activeJobs = computed(() =>
  Object.values(analysisById.value).filter((item) =>
    ["QUEUED", "RUNNING"].includes(item.status) ||
    forcedAnalysisPollIds.value.has(item.id),
  ),
);

const activeChatJobs = computed(() =>
  Object.values(chatJobsById.value).filter((item) =>
    ["QUEUED", "RUNNING"].includes(item.status),
  ),
);

const activeComposerChatJob = computed<ChatReplyJob | null>(() =>
  [...activeChatJobs.value]
    .sort((left, right) => right.createdAt.localeCompare(left.createdAt))[0] ?? null,
);

function isInitialGreeting(item: ConversationMessage, index: number) {
  if (index !== 0 || item.role !== "ASSISTANT") return false;
  return item.content.includes("지금 어떤 일을 해왔고 앞으로 어디로 가고 싶은지부터")
    && item.content.includes("공고가 있다면 나중에 첨부해도 되고");
}

const visibleConversationMessages = computed(() =>
  (conversation.value?.messages ?? []).filter(
    (item, index) => !isInitialGreeting(item, index),
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

function postingReviewFor(item: ConversationMessage) {
  return messageJob(item)?.result?.postingReview ?? null;
}

function answeredQuestionForMessage(
  item: ConversationMessage,
): AnalysisJob["questionHistory"][number] | null {
  if (item.role !== "USER" || item.kind !== "ANALYSIS_STATUS") return null;
  const questionId =
    typeof item.metadata.questionId === "string"
      ? item.metadata.questionId
      : null;
  if (!questionId) return null;
  return (
    messageJob(item)?.questionHistory.find(
      (question) => question.id === questionId,
    ) ?? null
  );
}

function isPostingReviewQuestion(item: ConversationMessage) {
  return answeredQuestionForMessage(item)?.key.startsWith("posting-review-") ?? false;
}

function v3AssessmentFor(item: ConversationMessage) {
  const fit = messageJob(item)?.result?.fit as
    | { assessment?: Record<string, any> }
    | undefined;
  return fit?.assessment ?? null;
}

function v3ProjectFor(item: ConversationMessage) {
  return (messageJob(item)?.result as Record<string, any> | null)?.projectBlueprint ?? null;
}

function v3ResultTitle(item: ConversationMessage) {
  const review = postingReviewFor(item);
  const project = v3ProjectFor(item);
  if (project?.title) return project.title;
  if (review?.companyName && review.positionTitle) {
    return `${review.companyName} · ${review.positionTitle} 준비 분석`;
  }
  return "회사 맞춤 프로젝트와 로드맵 초안이 준비됐어요";
}

function analysisLifecycleStatus(item: ConversationMessage) {
  const currentJob = messageJob(item);
  if (currentJob?.analysisProvider === "UNIFIED") {
    const structured = currentJob.result?.structuredPosting as
      | { postingStatus?: string }
      | undefined;
    return structured?.postingStatus ?? "UNKNOWN";
  }
  return currentJob?.result?.job?.lifecycleStatus ?? "UNKNOWN";
}

function isClosedAnalysis(item: ConversationMessage) {
  return ["EXPIRED", "CLOSED"].includes(analysisLifecycleStatus(item));
}

function readinessValue(value: unknown, emptyLabel = "계산 보류") {
  return typeof value === "number" ? value + "%" : emptyLabel;
}

function requiredVerificationValue(assessment: any) {
  const metrics = assessment?.metrics;
  if (!metrics || (metrics.requiredTotal ?? 0) === 0) return "계산 불가";
  return `${metrics.requiredVerifiedMet ?? 0}/${metrics.requiredTotal}`;
}

function readinessUnavailableMessage(assessment: any) {
  const reason = assessment?.metrics?.readinessUnavailableReason;
  if (reason === "NO_REQUIRED_REQUIREMENTS") {
    return "필수 요건을 계산 대상으로 구성하지 못했습니다. 공고 원문을 다시 확인하거나 재분석해 주세요.";
  }
  if (reason === "REQUIRED_EVIDENCE_UNKNOWN") {
    const total = assessment?.metrics?.requiredTotal ?? 0;
    return `커리어 자료는 등록되어 있지만 이번 공고의 필수 ${total}개 요건과 연결된 근거를 아직 확인하지 못해 준비도 계산을 보류했어요.`;
  }
  return "";
}

function followAnalysisUntilSettled(id: string) {
  const next = new Set(forcedAnalysisPollIds.value);
  next.add(id);
  forcedAnalysisPollIds.value = next;
  forcedAnalysisPollDeadlines.set(id, Date.now() + 2 * 60 * 1000);
}

function stopFollowingAnalysis(id: string) {
  if (!forcedAnalysisPollIds.value.has(id)) return;
  const next = new Set(forcedAnalysisPollIds.value);
  next.delete(id);
  forcedAnalysisPollIds.value = next;
  forcedAnalysisPollDeadlines.delete(id);
}

function roadmapCompetenciesFor(item: ConversationMessage) {
  return (messageJob(item)?.proposal?.competencies ?? []).filter(
    (competency) => competency.roadmapEligible !== false,
  );
}

function experienceCompetenciesFor(item: ConversationMessage) {
  return (messageJob(item)?.proposal?.competencies ?? []).filter(
    (competency) =>
      competency.roadmapEligible === false && competency.kind === "EXPERIENCE",
  );
}

function qualitativeCompetenciesFor(item: ConversationMessage) {
  return (messageJob(item)?.proposal?.competencies ?? []).filter(
    (competency) =>
      competency.roadmapEligible === false && competency.kind !== "EXPERIENCE",
  );
}

function chatJobForMessage(item: ConversationMessage): ChatReplyJob | null {
  return (
    Object.values(chatJobsById.value).find(
      (job) => job.triggerMessageId === item.id,
    ) ?? null
  );
}

function agentResultForMessage(item: ConversationMessage): AgentChatResult {
  return item.role === "ASSISTANT"
    ? (item.metadata as AgentChatResult)
    : {};
}

function chatJobForAssistant(item: ConversationMessage): ChatReplyJob | null {
  const jobId = typeof item.metadata.chatReplyJobId === "string"
    ? item.metadata.chatReplyJobId
    : null;
  return jobId ? chatJobsById.value[jobId] ?? null : null;
}

function agentActionBusyKey(item: ConversationMessage, action: AgentProposedAction) {
  return `${chatJobForAssistant(item)?.id ?? "missing"}:${action.actionId}`;
}

function executedAgentAction(
  item: ConversationMessage,
  action: AgentProposedAction,
) {
  return agentResultForMessage(item).actionExecutions?.[action.actionId]
    ?? chatJobForAssistant(item)?.result.actionExecutions?.[action.actionId]
    ?? null;
}

function agentArtifactForMessage(item: ConversationMessage): AgentArtifact | null {
  const result = agentResultForMessage(item);
  const artifact = result.artifact ?? null;
  if (!artifact) return null;
  const equivalentProductType = {
    DIAGNOSIS: "DIAGNOSIS",
    COMPARISON: "COMPARISON",
    INTERVIEW_SET: "INTERVIEW_SET",
    COVER_LETTER_DRAFT: "COVER_LETTER_DRAFT",
    APPLICATION_PLAN: "APPLICATION_PLAN",
    JOB_DISCOVERY_PLAN: "JOB_RECOMMENDATIONS",
  }[artifact.artifactType];
  return result.workProducts?.some(
    (product) => product.productType === equivalentProductType,
  )
    ? null
    : artifact;
}

function visibleAgentWarnings(item: ConversationMessage) {
  // 섹션 헤더가 없는 공고도 전문 LLM 추출로 정상 처리된다. 내부 추출 전략 안내를
  // 사용자 확인이 필요한 실패처럼 노출하지 않는다.
  const informationalCodes = new Set([
    "no_requirement_sections",
    "unrelated_tail_dropped",
    "planner_requested_agents_reconciled",
  ]);
  return (agentResultForMessage(item).warnings ?? []).filter(
    (warning) => !informationalCodes.has(warning.code),
  );
}

function agentProgressForMessage(item: ConversationMessage): AgentProgressEvent[] {
  return agentResultForMessage(item).progress ?? [];
}

function artifactSectionTitle(section: Record<string, unknown>, index: number) {
  const title = section.title ?? section.heading ?? section.label ?? section.name;
  return typeof title === "string" && title.trim() ? title : `항목 ${index + 1}`;
}

function artifactSectionBody(section: Record<string, unknown>) {
  const values = Object.entries(section)
    .filter(([key]) => !["title", "heading", "label", "name"].includes(key))
    .map(([, value]) => {
      if (Array.isArray(value)) return value.map(String).join("\n");
      if (value && typeof value === "object") return JSON.stringify(value, null, 2);
      return value == null ? "" : String(value);
    })
    .filter(Boolean);
  return values.join("\n");
}

function postingLabel(posting: Posting) {
  return [posting.companyName, posting.roleTitle].filter(Boolean).join(" · ") || "이름 없는 공고";
}

function togglePosting(id: string) {
  if (selectedPostingIds.value.includes(id)) {
    selectedPostingIds.value = selectedPostingIds.value.filter((item) => item !== id);
  } else if (selectedPostingIds.value.length < 5) {
    selectedPostingIds.value = [...selectedPostingIds.value, id];
  }
}

function toggleCareerSource(id: string) {
  if (selectedCareerSourceIds.value.includes(id)) {
    selectedCareerSourceIds.value = selectedCareerSourceIds.value.filter(
      (item) => item !== id,
    );
  } else if (selectedCareerSourceIds.value.length < 5) {
    selectedCareerSourceIds.value = [...selectedCareerSourceIds.value, id];
  }
}

function contextRequirementText() {
  const requirements: string[] = [];
  if (selectedMode.value.postingMinimum) {
    requirements.push(`공고 ${selectedMode.value.postingMinimum}개 이상`);
  }
  if (selectedMode.value.sourceMinimum) {
    requirements.push(`커리어 자료 ${selectedMode.value.sourceMinimum}개 이상`);
  }
  return requirements.length ? `${requirements.join(", ")}를 선택해 주세요.` : "자료 선택 없이 시작할 수 있어요.";
}

async function loadAgentAssets() {
  assetsLoading.value = true;
  try {
    const [postings, sources] = await Promise.all([
      api.postings(),
      api.careerSources(false),
    ]);
    availablePostings.value = postings.filter((item) => !item.archivedAt);
    availableCareerSources.value = sources.filter((item) => !item.archivedAt);
    selectedPostingIds.value = selectedPostingIds.value.filter((id) =>
      availablePostings.value.some((item) => item.id === id),
    );
    selectedCareerSourceIds.value = selectedCareerSourceIds.value.filter((id) =>
      availableCareerSources.value.some((item) => item.id === id),
    );
  } finally {
    assetsLoading.value = false;
  }
}

function applyRouteAgentContext() {
  // 담당 에이전트는 사용자가 고르지 않고 오케스트레이터가 대화에 맞춰 선택한다.
  agentMode.value = "AUTO";
  selectedPostingIds.value = [];
  selectedCareerSourceIds.value = [];
  showAgentContext.value = false;
}

function verdictLabel(verdict?: string) {
  if (verdict === "REVIEW_REQUIRED") return "판정 보류";
  if (verdict === "UNKNOWN") return "판정 보류";
  if (verdict === "APPLY_NOW") return "지금 지원";
  if (verdict === "STRENGTHEN_THEN_APPLY") return "보강 후 지원";
  if (verdict === "ALTERNATIVE_FIRST" || verdict === "ALTERNATIVE_PATH") {
    return "대체 경로 우선";
  }
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
  showNewMessages.value = !isNearMessageBottom();
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
    .map((item) => {
      const last = item.progressEvents[item.progressEvents.length - 1];
      return [
        item.id,
        item.status,
        item.stage,
        last?.agentId ?? "",
        last?.status ?? "",
      ].join(":");
    })
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
  conversationPage.value = 0;
  const page = await api.searchConversations({
    query: conversationQuery.value.trim(),
    status: "ACTIVE",
    page: 0,
    size: 30,
  });
  conversations.value = page.items.filter((item) =>
    conversationStatus.value === "LEARNING" ? learningChats.isLearning(item) : !learningChats.isLearning(item)
  );
  conversationTotal.value = conversations.value.length;
  if (conversationStatus.value === "LEARNING") {
    conversation.value = null;
    return;
  }
  const selected =
    preferredId ??
    (conversation.value?.status === conversationStatus.value
      ? conversation.value.id
      : undefined) ??
    conversations.value[0]?.id;
  if (selected) {
    await openConversation(selected);
  } else {
    conversation.value = null;
    if (
      conversationStatus.value === "ACTIVE" &&
      !conversationQuery.value.trim() &&
      typeof route.query.new !== "string"
    ) {
      await router.replace({ name: "home", query: { focus: "chat" } });
    }
  }
}

function handleConversationSearch(event: Event) {
  const detail = (event as CustomEvent<{ query?: string }>).detail;
  conversationQuery.value = detail?.query ?? "";
  void loadConversations();
}

async function loadMoreConversations() {
  const nextPage = conversationPage.value + 1;
  const page = await api.searchConversations({
    query: conversationQuery.value.trim(),
    status: "ACTIVE",
    page: nextPage,
    size: 30,
  });
  conversations.value = [...conversations.value, ...page.items];
  conversationPage.value = nextPage;
  conversationTotal.value = page.total;
}

async function createConversation() {
  error.value = "";
  const created = await api.createConversation();
  conversation.value = created;
  await refreshConversationList();
  await scrollToBottom("auto");
}

async function createConversationFromRoute() {
  await createConversation();
  const prompt = typeof route.query.prompt === "string" ? route.query.prompt.trim() : "";
  const requestedAction = route.query.action;
  if (prompt) {
    message.value = prompt.slice(0, CHAT_INPUT_MAX_CHARS);
    await sendText();
  }
  if (requestedAction === "posting") startPostingAnalysis();
  if (conversation.value) {
    await router.replace({
      name: "chat",
      query: { conversationId: conversation.value.id },
    });
  }
}

async function refreshConversationList() {
  const page = await api.searchConversations({
    query: conversationQuery.value.trim(),
    status: "ACTIVE",
    page: 0,
    size: Math.max(30, conversations.value.length),
  });
  conversations.value = page.items.filter((item) =>
    conversationStatus.value === "LEARNING" ? learningChats.isLearning(item) : !learningChats.isLearning(item)
  );
  conversationTotal.value = conversations.value.length;
}

async function openConversationFromList(item: ConversationSummary) {
  const planId = learningChats.planIdFor(item);
  if (planId) {
    markConversationSeen(item.id, item.lastMessageAt);
    await router.push({ name: "learning", params: { planId } });
    return;
  }
  await openConversation(item.id);
}

async function openConversation(id: string) {
  const requestSequence = ++conversationRequestSequence;
  const previousId = conversation.value?.id;
  const loaded = await api.conversation(id);
  if (requestSequence !== conversationRequestSequence) return;
  conversation.value = loaded;
  markConversationSeen(loaded.id, loaded.lastMessageAt);
  message.value = window.localStorage.getItem(`${CHAT_COMPOSER_DRAFT_PREFIX}${id}`) ?? "";
  if (previousId !== id) {
    agentMode.value = "AUTO";
    selectedPostingIds.value = [];
    selectedCareerSourceIds.value = [];
    showAgentContext.value = false;
  }
  await hydrateJobs();
  await scrollToBottom("auto");
}

async function loadOlderMessages() {
  const current = conversation.value;
  const first = current?.messages[0];
  const list = messageList.value;
  if (!current?.hasOlderMessages || !first || loadingOlderMessages.value) return;
  loadingOlderMessages.value = true;
  const previousHeight = list?.scrollHeight ?? 0;
  try {
    const page = await api.conversationMessagesBefore(
      current.id,
      first.createdAt,
      first.id,
      100,
    );
    if (conversation.value?.id !== current.id) return;
    conversation.value.messages = [...page.items, ...conversation.value.messages];
    conversation.value.hasOlderMessages = page.hasMore;
    await nextTick();
    if (list) list.scrollTop += list.scrollHeight - previousHeight;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "이전 메시지를 불러오지 못했습니다.";
  } finally {
    loadingOlderMessages.value = false;
  }
}

async function renameConversation(item: ConversationSummary) {
  const title = await productDialog.prompt({
    title: "대화 이름 변경",
    message: "이 대화를 나중에 쉽게 찾을 수 있는 이름으로 바꿉니다.",
    confirmLabel: "저장",
    input: { label: "대화 이름", value: item.title, maxLength: 120 },
  });
  if (title === null || !title.trim() || title.trim() === item.title) return;
  try {
    const updated = await api.renameConversation(item.id, title.trim());
    conversations.value = conversations.value.map((value) =>
      value.id === item.id ? updated : value,
    );
    if (conversation.value?.id === item.id) conversation.value.title = updated.title;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "대화 이름을 바꾸지 못했습니다.";
  }
}

async function toggleConversationArchive(item: ConversationSummary) {
  try {
    if (item.status === "ARCHIVED") await api.restoreConversation(item.id);
    else await api.archiveConversation(item.id);
    if (conversation.value?.id === item.id) conversation.value = null;
    await loadConversations();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "대화 보관 상태를 바꾸지 못했습니다.";
  }
}

async function restoreCurrentConversation() {
  if (!conversation.value || conversation.value.status !== "ARCHIVED") return;
  try {
    await api.restoreConversation(conversation.value.id);
    conversation.value.status = "ACTIVE";
    conversationStatus.value = "ACTIVE";
    await loadConversations();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "대화를 복원하지 못했습니다.";
  }
}

async function deleteConversation(id: string) {
  if (!await productDialog.confirm({ title: "대화 삭제", message: "이 대화 세션을 삭제할까요? 연결된 공고와 분석 기록은 유지됩니다.", confirmLabel: "대화 삭제", danger: true })) {
    return;
  }
  error.value = "";
  try {
    await api.deleteConversation(id);
    const next = conversations.value.find((item) => item.id !== id)?.id;
    conversation.value = null;
    if (next) await loadConversations(next);
    else await router.replace({ name: "home", query: { focus: "chat" } });
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
  await executeAutomaticActions();
  schedulePoll();
}

async function executeAutomaticActions() {
  let conversationRefreshNeeded = false;
  for (const job of Object.values(chatJobsById.value)) {
    if (job.status !== "SUCCEEDED") continue;
    for (const action of job.result.proposedActions ?? []) {
      const previousExecution = job.result.actionExecutions?.[action.actionId];
      if (previousExecution) {
        if (previousExecution.resourceType === "POSTING_REVIEW") {
          const reviewKey = `${job.id}:${action.actionId}`;
          const reviewText = typeof previousExecution.result.reviewText === "string"
            ? previousExecution.result.reviewText.trim()
            : "";
          if (reviewText && !postingReviewEdits.value[reviewKey]) {
            postingReviewEdits.value[reviewKey] = reviewText;
          }
        }
        if (
          previousExecution.analysisJobId &&
          !analysisById.value[previousExecution.analysisJobId]
        ) {
          try {
            analysisById.value[previousExecution.analysisJobId] =
              await api.analysisJob(previousExecution.analysisJobId);
            conversationRefreshNeeded = true;
          } catch {
            // 다음 폴링 또는 화면 재진입에서 복구한다.
          }
        }
      }
    }
  }
  if (conversationRefreshNeeded && conversation.value) {
    conversation.value = await api.conversation(conversation.value.id);
    const createdIds = new Set(
      conversation.value.messages
        .map((item) => item.analysisJobId)
        .filter((id): id is string => Boolean(id)),
    );
    await Promise.all(
      [...createdIds].map(async (id) => {
        if (analysisById.value[id]) return;
        try {
          analysisById.value[id] = await api.analysisJob(id);
        } catch {
          // 다음 폴링 또는 화면 재진입에서 복구한다.
        }
      }),
    );
  }
}

function schedulePoll() {
  if (pollTimer) window.clearTimeout(pollTimer);
  if (activeJobs.value.length === 0 && activeChatJobs.value.length === 0) return;
  pollTimer = window.setTimeout(
    pollJobs,
    activeChatJobs.value.length > 0 ? 700 : 2500,
  );
}

async function pollJobs() {
  const followLatest = isNearMessageBottom();
  const previousSignature = messageUpdateSignature();
  const ids = activeJobs.value.map((item) => item.id);
  const chatIds = activeChatJobs.value.map((item) => item.id);
  try {
    await Promise.all(
      [
      ...ids.map(async (id) => {
        try {
          const refreshed = await api.analysisJob(id);
          analysisById.value[id] = refreshed;
          const deadline = forcedAnalysisPollDeadlines.get(id);
          if (
            ["SUCCEEDED", "FAILED", "CANCELLED"].includes(refreshed.status) ||
            (refreshed.status === "WAITING_FOR_INPUT" &&
              Boolean(refreshed.pendingQuestion)) ||
            (deadline !== undefined && Date.now() >= deadline)
          ) {
            stopFollowingAnalysis(id);
          }
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
      const currentId = conversation.value.id;
      const refreshed = await api.conversation(currentId);
      if (conversation.value?.id === currentId) {
        conversation.value = refreshed;
        markConversationSeen(currentId, refreshed.lastMessageAt);
      }
    }
    await executeAutomaticActions();
    await refreshConversationList();
    const contentChanged = previousSignature !== messageUpdateSignature();
    if (contentChanged) {
      if (followLatest) await scrollToBottom();
      else showNewMessages.value = true;
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "작업 상태를 갱신하지 못했습니다.";
  } finally {
    schedulePoll();
  }
}

async function attachResumeFile(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file || sending.value) return;
  if (file.size > 5 * 1024 * 1024) {
    error.value = "파일은 5MB 이하만 보낼 수 있습니다.";
    return;
  }
  if (!/\.(docx|txt|md)$/i.test(file.name)) {
    error.value = "TXT, MD, DOCX 파일만 보낼 수 있습니다.";
    return;
  }
  error.value = "";
  sending.value = true;
  let text = "";
  try {
    // docx는 서버가 텍스트를 추출한다(커리어 저장소에도 함께 등록됨). txt/md는 브라우저에서 읽는다.
    text = /\.docx$/i.test(file.name)
      ? ((await api.uploadCareerSource(
          file,
          file.name.replace(/\.[^.]+$/, ""),
        )).rawText || "").trim()
      : (await file.text()).trim();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "파일을 읽지 못했습니다.";
    return;
  } finally {
    sending.value = false;
  }
  if (text.length < 20) {
    error.value = "파일에서 읽은 내용이 너무 짧습니다.";
    return;
  }
  message.value = text.slice(0, CHAT_INPUT_MAX_CHARS);
  await sendText();
}

async function sendText() {
  const content = message.value.trim();
  if (!content || !conversation.value || sending.value) return;
  if (content.length > CHAT_INPUT_MAX_CHARS) {
    error.value = `한 번에 보낼 수 있는 최대 길이는 ${CHAT_INPUT_MAX_CHARS.toLocaleString()}자예요. 내용을 나누어 보내주세요.`;
    return;
  }
  if (!contextReady.value) {
    showAgentContext.value = true;
    error.value = contextRequirementText();
    return;
  }
  const conversationId = conversation.value.id;
  const optimisticId = `local-${crypto.randomUUID()}`;
  const optimistic: ConversationMessage = {
    id: optimisticId,
    role: "USER",
    kind: "TEXT",
    content,
    postingId: null,
    analysisJobId: null,
    metadata: {
      optimistic: true,
      agentContext: currentAgentContext.value,
    },
    createdAt: new Date().toISOString(),
  };
  conversation.value.messages.push(optimistic);
  error.value = "";
  message.value = "";
  sending.value = true;
  await scrollToBottom();
  try {
    const result = await api.sendMessage(
      conversationId,
      content,
      undefined,
      currentAgentContext.value,
    );
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

function postingLengthMessage(length: number) {
  return `분석에 사용할 내용이 시스템 제한을 넘었어요. 현재 ${length.toLocaleString()}자이며 최대 ${POSTING_TEXT_MAX_CHARS.toLocaleString()}자예요.`;
}

async function answerAgentConfirmation(option: string) {
  if (sending.value) return;
  message.value = option;
  await sendText();
}

function handledPostingReviews(): Set<string> {
  try {
    const values = JSON.parse(
      window.localStorage.getItem(HANDLED_POSTING_REVIEW_KEY) ?? "[]",
    ) as string[];
    return new Set(values.filter((value) => typeof value === "string"));
  } catch {
    return new Set();
  }
}

function markPostingReviewHandled(reviewKey = activePostingReviewKey.value) {
  if (!reviewKey) return;
  const values = handledPostingReviews();
  values.add(reviewKey);
  window.localStorage.setItem(
    HANDLED_POSTING_REVIEW_KEY,
    JSON.stringify([...values].slice(-100)),
  );
  if (activePostingReviewKey.value === reviewKey) activePostingReviewKey.value = null;
}

function postingReviewKey(item: ConversationMessage, action: AgentProposedAction) {
  return `${chatJobForAssistant(item)?.id ?? "missing"}:${action.actionId}`;
}

function postingReviewExecution(
  item: ConversationMessage,
  action: AgentProposedAction,
): AgentActionExecution | null {
  const execution = executedAgentAction(item, action);
  return execution?.resourceType === "POSTING_REVIEW" ? execution : null;
}

function postingReviewText(item: ConversationMessage, action: AgentProposedAction) {
  const key = postingReviewKey(item, action);
  if (postingReviewEdits.value[key]) return postingReviewEdits.value[key];
  const execution = postingReviewExecution(item, action);
  return typeof execution?.result.reviewText === "string"
    ? execution.result.reviewText
    : "";
}

function updatePostingReviewText(
  item: ConversationMessage,
  action: AgentProposedAction,
  event: Event,
) {
  postingReviewEdits.value[postingReviewKey(item, action)] =
    (event.target as HTMLTextAreaElement).value;
}

async function confirmPostingReviewExecution(
  item: ConversationMessage,
  action: AgentProposedAction,
) {
  const execution = postingReviewExecution(item, action);
  if (!conversation.value || !execution) return;
  const key = postingReviewKey(item, action);
  if (execution.analysisJobId) {
    // 백엔드가 액션 실행 시점에 V3 등록·원문 확인·분석 시작까지 이어 두었다.
    // 같은 원문을 여기서 다시 등록하지 않고 진행만 지켜본다.
    actionJobId.value = key;
    error.value = "";
    try {
      analysisById.value[execution.analysisJobId] = await api.analysisJob(
        execution.analysisJobId,
      );
      markPostingReviewHandled(key);
    } catch (cause) {
      error.value = cause instanceof Error
        ? cause.message
        : "분석 상태를 불러오지 못했습니다.";
    } finally {
      actionJobId.value = null;
    }
    return;
  }
  const originalText = typeof execution.result.rawText === "string"
    ? execution.result.rawText.trim()
    : "";
  const reviewedText = postingReviewText(item, action).trim();
  if (originalText.length < 20 || reviewedText.length < 20) {
    error.value = "확인할 공고 내용을 불러오지 못했습니다.";
    return;
  }
  if (reviewedText.length > POSTING_TEXT_MAX_CHARS) {
    error.value = postingLengthMessage(reviewedText.length);
    return;
  }

  actionJobId.value = key;
  error.value = "";
  try {
    const acquired = await api.acquireV3Source({
      inputType: "TEXT",
      entryPoint: "CHAT",
      extractionRevision: 1,
      text: originalText,
    });
    await startVerifiedPostingAnalysis(
      acquired,
      reviewedText,
      acquired.sourceDocument.rawText,
      "STRUCTURE_CORRECTION",
    );
    markPostingReviewHandled(key);
  } catch (cause) {
    error.value = cause instanceof Error
      ? cause.message
      : "확인한 공고로 분석을 시작하지 못했습니다.";
  } finally {
    actionJobId.value = null;
  }
}

function visibleProposedActions(item: ConversationMessage) {
  // 공고 분석은 확인 박스 없이 자동 실행되므로(executeAutomaticActions) 카드를 띄우지 않는다.
  return (agentResultForMessage(item).proposedActions ?? []).filter(
    (action) => action.actionType !== "ANALYZE_POSTING",
  );
}

async function executeAgentAction(
  item: ConversationMessage,
  action: AgentProposedAction,
) {
  const job = chatJobForAssistant(item);
  if (!job || executedAgentAction(item, action)) return;
  const busyKey = agentActionBusyKey(item, action);
  actionJobId.value = busyKey;
  error.value = "";
  try {
    const execution = await api.executeChatAction(job.id, action.actionId);
    const route = execution.result?.route;
    if (execution.resourceType === "POSTING_REVIEW") {
      const reviewKey = `${job.id}:${action.actionId}`;
      const reviewText = typeof execution.result.reviewText === "string"
        ? execution.result.reviewText.trim()
        : "";
      if (reviewText) postingReviewEdits.value[reviewKey] = reviewText;
    }
    if (conversation.value) {
      conversation.value = await api.conversation(conversation.value.id);
      await hydrateJobs();
    }
    if (typeof route === "string") await router.push(route);
    await scrollToBottom();
  } catch (cause) {
    error.value = cause instanceof Error
      ? cause.message
      : "AI가 제안한 작업을 실행하지 못했습니다.";
  } finally {
    actionJobId.value = null;
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

async function cancelChat(job: ChatReplyJob) {
  actionJobId.value = job.id;
  error.value = "";
  try {
    await api.cancelChatReply(job.id);
    chatJobsById.value[job.id] = await api.chatReplyJob(job.id);
    schedulePoll();
  } catch (cause) {
    error.value = cause instanceof Error
      ? cause.message
      : "답변 생성을 취소하지 못했습니다.";
  } finally {
    actionJobId.value = null;
  }
}

function selectAttachedSourceType(type: "TEXT" | "URL") {
  sourceType.value = type;
  attachedV3Source.value = null;
  attachedExtractedText.value = "";
  attachedPostingReviewState.value = "NONE";
  error.value = "";
}

async function openPostingModal() {
  if (!conversation.value) return;
  showPosting.value = true;
  const conversationId = conversation.value.id;
  try {
    const stored = JSON.parse(
      window.localStorage.getItem(CHAT_POSTING_DRAFT_KEY) ?? "null",
    ) as {
      conversationId?: string;
      sourceType?: "TEXT" | "URL";
      sourceUrl?: string;
      rawText?: string;
      sourceId?: string;
      extractedText?: string;
      reviewState?: "NONE" | "PENDING" | "READY";
      reviewKey?: string;
    } | null;
    if (!stored || stored.conversationId !== conversationId) {
      sourceUrl.value = "";
      rawText.value = "";
      attachedV3Source.value = null;
      attachedExtractedText.value = "";
      attachedPostingReviewState.value = "NONE";
      activePostingReviewKey.value = null;
      return;
    }
    sourceType.value = stored.sourceType ?? "TEXT";
    sourceUrl.value = stored.sourceUrl ?? "";
    rawText.value = stored.rawText ?? "";
    attachedExtractedText.value = stored.extractedText ?? "";
    attachedPostingReviewState.value = stored.reviewState ?? "NONE";
    activePostingReviewKey.value = stored.reviewKey ?? null;
    if (stored.sourceId) {
      const restored = await api.v3Source(stored.sourceId);
      if (conversation.value?.id !== conversationId) return;
      attachedV3Source.value = restored;
      if (!attachedExtractedText.value) {
        attachedExtractedText.value = restored.sourceDocument.rawText;
      }
      if (!rawText.value) rawText.value = restored.sourceDocument.rawText;
    }
  } catch {
    attachedV3Source.value = null;
    attachedExtractedText.value = "";
    attachedPostingReviewState.value = "NONE";
    activePostingReviewKey.value = null;
  }
}

function startPostingAnalysis() {
  if (!conversation.value || sending.value) return;
  sourceType.value = "TEXT";
  sourceUrl.value = "";
  rawText.value = "";
  attachedV3Source.value = null;
  attachedExtractedText.value = "";
  attachedPostingReviewState.value = "NONE";
  activePostingReviewKey.value = null;
  error.value = "";
  window.localStorage.removeItem(CHAT_POSTING_DRAFT_KEY);
  showPosting.value = true;
}

function closePostingModal() {
  showPosting.value = false;
}

function resetAttachedSource() {
  if (attachedPostingReviewState.value === "READY") markPostingReviewHandled();
  attachedV3Source.value = null;
  attachedExtractedText.value = "";
  attachedPostingReviewState.value = "NONE";
  error.value = "";
}

function canPrepareAttachedPosting() {
  return sourceType.value === "URL"
    ? sourceUrl.value.trim().length > 8
    : rawText.value.trim().length >= 20
      && rawText.value.trim().length <= POSTING_TEXT_MAX_CHARS;
}

async function prepareAttachedPosting() {
  if (!conversation.value || !canPrepareAttachedPosting() || sending.value) return;
  if (sourceType.value === "TEXT" && rawText.value.trim().length > POSTING_TEXT_MAX_CHARS) {
    error.value = postingLengthMessage(rawText.value.trim().length);
    return;
  }
  const analysisRequest = sourceType.value === "URL"
    ? `${sourceUrl.value.trim()}${POSTING_URL_ANALYSIS_SUFFIX}`
    : `${rawText.value.trim()}${POSTING_ANALYSIS_SUFFIX}`;
  showPosting.value = false;
  message.value = analysisRequest;
  await sendText();
  if (!message.value) {
    sourceUrl.value = "";
    rawText.value = "";
    attachedV3Source.value = null;
    attachedExtractedText.value = "";
    attachedPostingReviewState.value = "NONE";
    activePostingReviewKey.value = null;
    window.localStorage.removeItem(CHAT_POSTING_DRAFT_KEY);
  }
}

async function startVerifiedPostingAnalysis(
  source: V3SourceView,
  verifiedText: string,
  extractedText: string,
  correctionReason: "STRUCTURE_CORRECTION" | "OTHER" = "OTHER",
) {
  const conversationId = conversation.value?.id;
  if (!conversationId) throw new Error("분석을 연결할 대화를 찾을 수 없습니다.");
  const changed = verifiedText.trim() !== extractedText.trim();
  await api.verifyV3Source(source.id, {
    verifiedText: verifiedText.trim(),
    corrections: changed
      ? [{
          field: "verifiedText",
          before: extractedText,
          after: verifiedText.trim(),
          reason: correctionReason,
        }]
      : [],
    verifiedBy: "USER",
  });
  const result = await api.startV3Analysis(source.id, conversationId);
  if (result.analysisJobId) {
    analysisById.value[result.analysisJobId] = await api.analysisJob(
      result.analysisJobId,
    );
  }
  showPosting.value = false;
  markPostingReviewHandled();
  sourceUrl.value = "";
  rawText.value = "";
  attachedV3Source.value = null;
  attachedExtractedText.value = "";
  attachedPostingReviewState.value = "NONE";
  window.localStorage.removeItem(CHAT_POSTING_DRAFT_KEY);
  await openConversation(conversationId);
  await refreshConversationList();
}

async function confirmAttachedPosting() {
  if (!conversation.value || !attachedV3Source.value || rawText.value.trim().length < 20) return;
  if (rawText.value.trim().length > POSTING_TEXT_MAX_CHARS) {
    error.value = postingLengthMessage(rawText.value.trim().length);
    return;
  }
  sending.value = true;
  error.value = "";
  try {
    const source = attachedV3Source.value;
    const verifiedText = rawText.value.trim();
    await startVerifiedPostingAnalysis(
      source,
      verifiedText,
      attachedExtractedText.value,
      attachedPostingReviewState.value === "READY"
        ? "STRUCTURE_CORRECTION"
        : "OTHER",
    );
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "공고를 등록하지 못했습니다.";
  } finally {
    sending.value = false;
  }
}

async function confirmPostingReview(job: AnalysisJob) {
  if (!job.pendingQuestion) return;
  answerSelections.value[job.id] = "CONFIRM";
  await answerAnalysisQuestion(job, "PROVIDED");
}

async function revisePostingReview(job: AnalysisJob) {
  const originalText = job.result?.postingReview?.originalText?.trim();
  if (!originalText) {
    error.value = "수정할 공고 원문을 찾을 수 없습니다.";
    return;
  }
  actionJobId.value = job.id;
  error.value = "";
  try {
    await api.cancelAnalysis(job.id);
    sourceType.value = "TEXT";
    sourceUrl.value = "";
    rawText.value = originalText;
    attachedV3Source.value = null;
    attachedExtractedText.value = "";
    showPosting.value = true;
    analysisById.value[job.id] = await api.analysisJob(job.id);
  } catch (cause) {
    error.value = cause instanceof Error
      ? cause.message
      : "공고 원문 수정 화면을 열지 못했습니다.";
  } finally {
    actionJobId.value = null;
  }
}

async function retry(job: AnalysisJob) {
  actionJobId.value = job.id;
  error.value = "";
  try {
    followAnalysisUntilSettled(job.id);
    await api.retryAnalysis(job.id);
    analysisById.value[job.id] = await api.analysisJob(job.id);
    schedulePoll();
  } catch (cause) {
    stopFollowingAnalysis(job.id);
    error.value = cause instanceof Error ? cause.message : "재시도하지 못했습니다.";
  } finally {
    actionJobId.value = null;
  }
}

async function cancelAnalysis(job: AnalysisJob) {
  if (!await productDialog.confirm({ title: "공고 분석 중단", message: "진행 중인 공고 분석을 취소할까요? 공고는 그대로 보관됩니다.", confirmLabel: "분석 중단", danger: true })) {
    return;
  }
  actionJobId.value = job.id;
  error.value = "";
  try {
    await api.cancelAnalysis(job.id);
    analysisById.value[job.id] = await api.analysisJob(job.id);
    schedulePoll();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "분석을 취소하지 못했습니다.";
  } finally {
    actionJobId.value = null;
  }
}

async function answerAnalysisQuestion(
  job: AnalysisJob,
  answerStatus: "PROVIDED" | "CONFIRMED_ABSENT" = "PROVIDED",
) {
  const question = job.pendingQuestion;
  if (answerStatus === "CONFIRMED_ABSENT") {
    answerSelections.value[job.id] = "없습니다.";
  }
  const value = answerSelections.value[job.id];
  if (!question || !value) return;
  actionJobId.value = job.id;
  error.value = "";
  try {
    followAnalysisUntilSettled(job.id);
    await api.answerAnalysisQuestion(job.id, question.id, value, answerStatus);
    delete answerSelections.value[job.id];
    analysisById.value[job.id] = await api.analysisJob(job.id);
    if (conversation.value) {
      conversation.value = await api.conversation(conversation.value.id);
    }
    schedulePoll();
    await scrollToBottom();
  } catch (cause) {
    stopFollowingAnalysis(job.id);
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
    if (job.analysisProvider === "UNIFIED") {
      if (!job.changeSetId) throw new Error("로드맵 초안을 찾을 수 없습니다.");
      await api.previewV3Roadmap(job.changeSetId);
      await router.push({
        name: "map",
        query: { provider: "unified", proposal: job.changeSetId, preview: "draft" },
      });
      return;
    }
    await api.approveAnalysis(job.id);
    analysisById.value[job.id] = await api.analysisJob(job.id);
    await router.push({
      name: "map",
      query: { posting: job.postingId, preview: "draft" },
    });
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "목표 공고에 추가하지 못했습니다.";
  } finally {
    actionJobId.value = null;
  }
}

async function reject(job: AnalysisJob) {
  if (!await productDialog.confirm({ title: "로드맵 변경안 거절", message: "이 변경안을 거절할까요? 공고와 분석 기록은 저장됩니다.", confirmLabel: "변경안 거절", danger: true })) return;
  actionJobId.value = job.id;
  error.value = "";
  try {
    if (job.analysisProvider === "UNIFIED") {
      if (!job.changeSetId) throw new Error("로드맵 초안을 찾을 수 없습니다.");
      await api.cancelV3Roadmap(job.changeSetId);
      analysisById.value[job.id] = await api.analysisJob(job.id);
      return;
    }
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

function resizeComposer() {
  const input = composerInput.value;
  if (!input) return;
  input.style.height = "auto";
  const style = window.getComputedStyle(input);
  const lineHeight = Number.parseFloat(style.lineHeight) || 24;
  const verticalPadding =
    Number.parseFloat(style.paddingTop) + Number.parseFloat(style.paddingBottom);
  const maximumHeight = lineHeight * 10 + verticalPadding;
  input.style.height = `${Math.min(input.scrollHeight, maximumHeight)}px`;
  input.style.overflowY = input.scrollHeight > maximumHeight ? "auto" : "hidden";
}

function refreshChatOnReturn() {
  if (document.visibilityState !== "visible" || !conversation.value) return;
  void hydrateJobs();
}

watch(message, () => {
  const conversationId = conversation.value?.id;
  if (conversationId) {
    const key = `${CHAT_COMPOSER_DRAFT_PREFIX}${conversationId}`;
    if (message.value) window.localStorage.setItem(key, message.value);
    else window.localStorage.removeItem(key);
  }
  void nextTick(resizeComposer);
});

watch(
  () => route.query.conversationId,
  async (id) => {
    if (typeof id !== "string" || loading.value) return;
    try {
      await openConversation(id);
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : "대화를 찾지 못했습니다.";
    }
  },
);

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
        await createConversationFromRoute();
      } catch (cause) {
        error.value = cause instanceof Error ? cause.message : "새 대화를 만들지 못했습니다.";
      }
    }
  },
);

onMounted(async () => {
  const requestedConversation = typeof route.query.conversationId === "string"
    ? route.query.conversationId
    : undefined;
  const results = await Promise.allSettled([
    loadConversations(requestedConversation),
    loadAgentAssets(),
  ]);
  const failed = results.find((result) => result.status === "rejected");
  if (failed?.status === "rejected") {
    error.value = failed.reason instanceof Error
      ? failed.reason.message
      : "일부 대화 정보를 불러오지 못했습니다.";
  }
  applyRouteAgentContext();
  loading.value = false;
  if (typeof route.query.new === "string") {
    try {
      await createConversationFromRoute();
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : "새 대화를 만들지 못했습니다.";
    }
  }
  await nextTick();
  resizeComposer();
  window.addEventListener("jobiss:conversation-search", handleConversationSearch);
  window.addEventListener("focus", refreshChatOnReturn);
  document.addEventListener("visibilitychange", refreshChatOnReturn);
});

onBeforeUnmount(() => {
  if (pollTimer) window.clearTimeout(pollTimer);
  window.removeEventListener("jobiss:conversation-search", handleConversationSearch);
  window.removeEventListener("focus", refreshChatOnReturn);
  document.removeEventListener("visibilitychange", refreshChatOnReturn);
});
</script>

<template>
  <main class="chat-workspace">
    <Teleport defer to="#sidebar-conversations">
      <aside class="conversation-sidebar" aria-label="대화 목록">
      <div class="conversation-status-tabs" role="tablist" aria-label="대화 상태">
        <button
          type="button"
          role="tab"
          :aria-selected="conversationStatus === 'ACTIVE'"
          :class="{ active: conversationStatus === 'ACTIVE' }"
          @click="conversationStatus = 'ACTIVE'; loadConversations()"
        >
          진행 중
        </button>
        <button
          type="button"
          role="tab"
          :aria-selected="conversationStatus === 'LEARNING'"
          :class="{ active: conversationStatus === 'LEARNING' }"
          @click="conversationStatus = 'LEARNING'; loadConversations()"
        >
          학습 채팅
        </button>
      </div>
      <div class="conversation-list">
        <div
          v-for="item in conversations"
          :key="item.id"
          class="conversation-link-row"
        >
          <button
            class="conversation-link"
            :class="{ active: conversation?.id === item.id }"
            type="button"
            @click="openConversationFromList(item)"
          >
            <span
              class="conversation-state-icon"
              :class="{
                'is-running': item.aiReplyPending,
                'is-failed': !item.aiReplyPending && item.latestJobFailed,
                'is-unread-complete': hasUnreadCompletedReply(item),
              }"
              :title="
                item.aiReplyPending
                  ? '답변 생성 중'
                  : item.latestJobFailed
                    ? '최근 작업 실패'
                    : undefined
              "
            >
              <MessageCircleMore :size="18" />
              <LoaderCircle v-if="item.aiReplyPending" class="spin" :size="11" />
              <CircleX v-else-if="item.latestJobFailed" :size="11" />
              <i v-else-if="hasUnreadCompletedReply(item)" aria-label="확인하지 않은 완료 응답" />
            </span>
            <span>
              <strong>{{ learningChats.isLearning(item) ? learningChats.titleFor(item) : item.title }}</strong>
              <small>{{ item.lastMessage || "새 대화" }}</small>
            </span>
            <time>{{ formatTime(item.lastMessageAt) }}</time>
          </button>
          <button
            class="conversation-row-action conversation-row-action--rename"
            type="button"
            :aria-label="`${item.title} 이름 변경`"
            title="이름 변경"
            @click="renameConversation(item)"
          >
            <Pencil :size="14" />
          </button>
          <button
            class="conversation-row-action conversation-row-action--archive"
            type="button"
            :aria-label="`${item.title} ${item.status === 'ARCHIVED' ? '복원' : '보관'}`"
            :title="item.status === 'ARCHIVED' ? '복원' : '보관'"
            @click="toggleConversationArchive(item)"
          >
            <ArchiveRestore v-if="item.status === 'ARCHIVED'" :size="14" />
            <Archive v-else :size="14" />
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
          {{ conversationStatus === "LEARNING" ? "아직 시작한 학습 채팅이 없습니다." : "첫 대화를 시작해 보세요." }}
        </div>
        <button
          v-if="conversations.length < conversationTotal"
          class="conversation-load-more"
          type="button"
          @click="loadMoreConversations"
        >
          이전 대화 더 보기
        </button>
      </div>
      </aside>
    </Teleport>

    <section class="chat-panel">
      <Teleport defer to="#app-topbar-center">
        <h1 class="app-page-title">{{ conversation?.title ?? "새 커리어 대화" }}</h1>
      </Teleport>
      <Teleport defer to="#app-topbar-actions">
        <span class="ai-state chat-save-state">
          <i />
          대화와 공고 분석 기록이 자동 저장됩니다
        </span>
      </Teleport>

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

        <button
          v-if="conversation?.hasOlderMessages"
          class="message-load-older"
          type="button"
          :disabled="loadingOlderMessages"
          @click="loadOlderMessages"
        >
          <LoaderCircle v-if="loadingOlderMessages" class="spin" :size="15" />
          <RefreshCw v-else :size="15" />
          이전 메시지 불러오기
        </button>

        <article
          v-for="item in visibleConversationMessages"
          :key="item.id"
          class="chat-message"
          :class="`chat-message--${item.role.toLowerCase()}`"
        >
          <div class="chat-bubble">
            <section
              v-if="answeredQuestionForMessage(item)"
              class="answered-analysis-context"
            >
              <V3PostingReviewCard
                v-if="isPostingReviewQuestion(item) && postingReviewFor(item)"
                :review="postingReviewFor(item)!"
                confirmed
              />
              <div v-else class="answered-analysis-context__question">
                <span><CircleHelp :size="21" /></span>
                <div>
                  <small>
                    JOBIS 확인 질문 · {{ answeredQuestionForMessage(item)?.ordinal }}번째
                  </small>
                  <strong>{{ answeredQuestionForMessage(item)?.text }}</strong>
                  <em><Check :size="14" /> 답변 완료</em>
                </div>
              </div>
            </section>
            <div class="chat-message__body">
              <AgentMessageContent
                v-if="item.role === 'ASSISTANT'"
                class="chat-message__content"
                :content="item.content"
              />
              <p v-else class="chat-message__content">{{ item.content }}</p>
              <time>{{ formatTime(item.createdAt) }}</time>
            </div>

            <AgentExecutionMap
              v-if="agentResultForMessage(item).plan?.agents?.length"
              compact
              :plan="agentResultForMessage(item).plan"
              :events="agentProgressForMessage(item)"
            />

            <div
              v-if="agentResultForMessage(item).detailedStatus"
              class="agent-decision-status"
            >
              <Sparkles :size="15" />
              내부 판단 · {{ agentResultForMessage(item).detailedStatus }}
            </div>

            <details
              v-if="visibleAgentWarnings(item).length"
              class="agent-warnings"
            >
              <summary>
                일부 확인이 필요한 항목 {{ visibleAgentWarnings(item).length }}개
                <ChevronDown :size="15" />
              </summary>
              <p
                v-for="warning in visibleAgentWarnings(item)"
                :key="`${warning.agentId}-${warning.code}`"
              >
                <strong>{{ warning.agentId ?? "에이전트" }}</strong>
                {{ warning.message }}
              </p>
            </details>

            <section
              v-if="agentResultForMessage(item).workProducts?.length"
              class="agent-products"
            >
              <AgentWorkProductCard
                v-for="(product, productIndex) in agentResultForMessage(item).workProducts ?? []"
                :key="`${product.agentId}-${productIndex}`"
                :product="product"
              />
            </section>

            <section
              v-if="agentArtifactForMessage(item)"
              class="agent-artifact"
            >
              <header>
                <span><Sparkles :size="17" /></span>
                <div>
                  <small>{{ agentArtifactForMessage(item)?.artifactType }}</small>
                  <strong>{{ agentArtifactForMessage(item)?.title }}</strong>
                </div>
              </header>
              <p>{{ agentArtifactForMessage(item)?.summary }}</p>
              <details
                v-if="agentArtifactForMessage(item)?.sections.length"
                class="agent-artifact__sections"
              >
                <summary>
                  결과 자세히 보기
                  <ChevronDown :size="16" />
                </summary>
                <article
                  v-for="(section, sectionIndex) in agentArtifactForMessage(item)?.sections ?? []"
                  :key="sectionIndex"
                >
                  <strong>{{ artifactSectionTitle(section, sectionIndex) }}</strong>
                  <p>{{ artifactSectionBody(section) }}</p>
                </article>
              </details>
            </section>

            <details
              v-if="agentResultForMessage(item).replySources?.length"
              class="agent-sources"
            >
              <summary>
                답변 근거 {{ agentResultForMessage(item).replySources?.length }}개
                <ChevronDown :size="15" />
              </summary>
              <article
                v-for="source in agentResultForMessage(item).replySources ?? []"
                :key="`${source.sourceType}-${source.sourceId}-${source.title}`"
              >
                <small>{{ source.sourceType }}</small>
                <strong>{{ source.title }}</strong>
                <p v-if="source.excerpt">{{ source.excerpt }}</p>
              </article>
            </details>

            <section
              v-if="agentResultForMessage(item).pendingConfirmation"
              class="agent-confirmation"
            >
              <span><CircleHelp :size="20" /></span>
              <div>
                <strong>{{ agentResultForMessage(item).pendingConfirmation?.question }}</strong>
                <p>{{ agentResultForMessage(item).pendingConfirmation?.reason }}</p>
                <div>
                  <button
                    v-for="option in agentResultForMessage(item).pendingConfirmation?.options ?? []"
                    :key="option"
                    type="button"
                    :disabled="sending"
                    @click="answerAgentConfirmation(option)"
                  >
                    {{ option }}
                  </button>
                </div>
              </div>
            </section>

            <section
              v-if="visibleProposedActions(item).length"
              class="agent-proposals"
            >
              <strong>다음 행동</strong>
              <article
                v-for="action in visibleProposedActions(item)"
                :key="action.actionId"
              >
                <span>{{ action.label }}</span>
                <p>{{ action.description }}</p>
                <template v-if="executedAgentAction(item, action)">
                  <small>
                    {{ executedAgentAction(item, action)?.message ?? "요청을 준비했습니다." }}
                  </small>
                  <section
                    v-if="postingReviewExecution(item, action)"
                    class="posting-review-inline"
                  >
                    <div>
                      <strong>분석할 공고 내용 확인</strong>
                      <small>직무·경력·담당 업무·필수·우대 요건이 원문과 맞는지 확인해 주세요.</small>
                    </div>
                    <textarea
                      :value="postingReviewText(item, action)"
                      :disabled="handledPostingReviews().has(postingReviewKey(item, action))"
                      rows="12"
                      aria-label="분석할 공고 정리 내용"
                      @input="updatePostingReviewText(item, action, $event)"
                    />
                    <button
                      v-if="!handledPostingReviews().has(postingReviewKey(item, action))"
                      type="button"
                      :disabled="
                        actionJobId === postingReviewKey(item, action) ||
                        postingReviewText(item, action).trim().length < 20
                      "
                      @click="confirmPostingReviewExecution(item, action)"
                    >
                      <LoaderCircle
                        v-if="actionJobId === postingReviewKey(item, action)"
                        :size="14"
                        class="spin"
                      />
                      <Check v-else :size="14" :stroke-width="3" />
                      이 내용으로 분석 시작
                    </button>
                    <span v-else class="posting-review-inline__confirmed">
                      <CheckCircle2 :size="16" /> 확인한 내용으로 분석을 시작했습니다.
                    </span>
                  </section>
                </template>
                <template v-else>
                  <small v-if="action.requiresConsent">확인하기 전에는 실행하지 않습니다</small>
                  <button
                    type="button"
                    :disabled="
                      !chatJobForAssistant(item) ||
                      actionJobId === agentActionBusyKey(item, action)
                    "
                    @click="executeAgentAction(item, action)"
                  >
                    <LoaderCircle
                      v-if="actionJobId === agentActionBusyKey(item, action)"
                      :size="14"
                      class="spin"
                    />
                    <Check v-else :size="14" :stroke-width="3" />
                    {{ action.label }}
                  </button>
                </template>
              </article>
            </section>

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
                <button
                  class="press-button press-button--ghost analysis-card__cancel"
                  type="button"
                  :disabled="actionJobId === messageJob(item)!.id"
                  @click="cancelAnalysis(messageJob(item)!)"
                >
                  <LoaderCircle
                    v-if="actionJobId === messageJob(item)!.id"
                    class="spin"
                    :size="16"
                  />
                  <X v-else :size="16" />
                  분석 취소
                </button>
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
                  <V3PostingReviewCard
                    v-if="
                      messageJob(item)?.stage === 'AWAITING_POSTING_CONFIRMATION' &&
                      postingReviewFor(item)
                    "
                    :review="postingReviewFor(item)!"
                    :busy="actionJobId === messageJob(item)!.id"
                    allow-revision
                    @confirm="confirmPostingReview(messageJob(item)!)"
                    @revise="revisePostingReview(messageJob(item)!)"
                    @cancel="cancelAnalysis(messageJob(item)!)"
                  />
                  <template v-else>
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
                  <textarea
                    v-if="messageJob(item)?.pendingQuestion?.inputType === 'TEXT'"
                    v-model="answerSelections[messageJob(item)!.id]"
                    class="analysis-question-text analysis-question-text--chat"
                    rows="4"
                    maxlength="2000"
                    placeholder="실제 경험과 근거를 구체적으로 적어주세요."
                  />
                  <small
                    v-if="messageJob(item)?.pendingQuestion?.inputType === 'TEXT'"
                    class="analysis-question-count"
                  >
                    {{ (answerSelections[messageJob(item)!.id] ?? '').length }}/2,000
                  </small>
                  <button
                    v-if="
                      messageJob(item)?.pendingQuestion?.inputType === 'TEXT' &&
                      messageJob(item)?.pendingQuestion?.absenceScope !== 'NONE'
                    "
                    class="analysis-question-absence"
                    type="button"
                    :disabled="actionJobId === messageJob(item)!.id"
                    @click="
                      answerAnalysisQuestion(
                        messageJob(item)!,
                        'CONFIRMED_ABSENT',
                      )
                    "
                  >
                    해당 경험 없음
                  </button>
                  <div v-else class="analysis-question-options analysis-question-options--chat">
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
                    @click="answerAnalysisQuestion(messageJob(item)!, 'PROVIDED')"
                  >
                    <LoaderCircle
                      v-if="actionJobId === messageJob(item)!.id"
                      class="spin"
                      :size="17"
                    />
                    <Check v-else :size="17" />
                    답변하고 분석 계속하기
                  </button>
                  <button
                    class="press-button press-button--ghost"
                    type="button"
                    :disabled="actionJobId === messageJob(item)!.id"
                    @click="cancelAnalysis(messageJob(item)!)"
                  >
                    <X :size="16" /> 분석 취소
                  </button>
                  </template>
                </div>
              </template>

              <template v-else-if="messageJob(item)?.status === 'CANCELLED'">
                <div class="analysis-card__state analysis-card__state--cancelled">
                  <X :size="22" />
                  <div>
                    <strong>진행 중이던 분석을 취소했어요</strong>
                    <span>공고는 보관되어 있습니다. 필요하면 같은 공고로 다시 시작할 수 있어요.</span>
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

              <template v-else-if="messageJob(item)?.status === 'FAILED'">
                <div class="analysis-card__state analysis-card__state--error">
                  <CircleAlert :size="22" />
                  <div>
                    <strong>커리어 적합도 분석을 마치지 못했어요</strong>
                    <span>공고는 안전하게 저장되어 있어요. 같은 공고로 다시 분석할 수 있습니다.</span>
                    <details v-if="messageJob(item)?.errorMessage" class="analysis-error-details">
                      <summary>오류 자세히 보기</summary>
                      <p>{{ messageJob(item)?.errorMessage }}</p>
                    </details>
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
                <div
                  v-if="messageJob(item)?.analysisProvider === 'UNIFIED'"
                  class="analysis-verdict analysis-verdict--v3"
                >
                  <span>{{ verdictLabel(v3AssessmentFor(item)?.verdictProposal) }}</span>
                  <h3>{{ v3ResultTitle(item) }}</h3>
                  <p>
                    위 판정은 공고 적합도·갭 분석 결과이며, 준비 경로는 별도의 로드맵 초안으로 만들었습니다.
                  </p>
                  <p v-if="isClosedAnalysis(item)" class="analysis-goal-mode-note">
                    모집은 마감되었지만 다음 채용을 대비하는 준비 목표로 등록할 수 있어요.
                  </p>
                  <div class="analysis-verdict__metrics">
                    <small>
                      필수 검증
                      <strong>{{ requiredVerificationValue(v3AssessmentFor(item)) }}</strong>
                    </small>
                    <small>
                      주장 준비도
                      <strong>{{ readinessValue(v3AssessmentFor(item)?.metrics?.claimedReadinessPercent) }}</strong>
                    </small>
                    <small v-if="v3AssessmentFor(item)?.metrics?.capabilityReadinessPercent != null">
                      필수 역량 준비도
                      <strong>{{ readinessValue(v3AssessmentFor(item)?.metrics?.capabilityReadinessPercent) }}</strong>
                    </small>
                    <small>
                      검증 준비도
                      <strong>{{ readinessValue(v3AssessmentFor(item)?.metrics?.verifiedReadinessPercent) }}</strong>
                    </small>
                  </div>
                  <p
                    v-if="readinessUnavailableMessage(v3AssessmentFor(item))"
                    class="analysis-goal-mode-note"
                  >
                    {{ readinessUnavailableMessage(v3AssessmentFor(item)) }}
                  </p>
                  <ul v-if="(v3AssessmentFor(item)?.gaps ?? []).length">
                    <li
                      v-for="gap in (v3AssessmentFor(item)?.gaps ?? []).slice(0, 4)"
                      :key="gap"
                    >
                      {{ gap }}
                    </li>
                  </ul>
                  <ul v-else-if="(v3AssessmentFor(item)?.uncertainties ?? []).length">
                    <li
                      v-for="uncertainty in (v3AssessmentFor(item)?.uncertainties ?? []).slice(0, 4)"
                      :key="uncertainty"
                    >
                      {{ uncertainty }} · 연결 근거 확인 필요
                    </li>
                  </ul>
                </div>
                <div v-else class="analysis-verdict">
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

                <details
                  v-if="
                    messageJob(item)?.analysisProvider === 'UNIFIED' &&
                    v3ProjectFor(item)?.tasks?.length
                  "
                  class="proposal-details"
                >
                  <summary>
                    회사 맞춤 프로젝트 구성 보기
                    <span>과제 {{ v3ProjectFor(item)?.tasks?.length ?? 0 }}개</span>
                    <ChevronDown :size="17" />
                  </summary>
                  <div class="proposal-section">
                    <h4>{{ v3ProjectFor(item)?.title }}</h4>
                    <p>{{ v3ProjectFor(item)?.objective }}</p>
                    <article
                      v-for="task in v3ProjectFor(item)?.tasks ?? []"
                      :key="task.taskKey"
                      class="proposal-row"
                    >
                      <span class="proposal-action proposal-action--create">
                        {{ task.necessity === 'REQUIRED' ? '필수' : '확장' }}
                      </span>
                      <div>
                        <strong>{{ task.title }}</strong>
                        <p>{{ task.objective }}</p>
                        <small>연결 역량 {{ task.capabilityKeys?.length ?? 0 }}개</small>
                      </div>
                    </article>
                  </div>
                </details>

                <details
                  v-if="
                    messageJob(item)?.analysisProvider !== 'UNIFIED' &&
                    messageJob(item)?.proposal
                  "
                  class="proposal-details"
                >
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
                    v-if="experienceCompetenciesFor(item).length"
                    class="proposal-section proposal-section--experience"
                  >
                    <h4>경력·수행 경험 조건</h4>
                    <p>
                      배워서 완료하는 기술 노드가 아니라, 실제 수행 이력으로 충족해야 하는 지원 조건입니다.
                    </p>
                    <article
                      v-for="competency in experienceCompetenciesFor(item)"
                      :key="competency.ref"
                      class="proposal-row"
                    >
                      <span class="proposal-action">조건</span>
                      <div>
                        <strong>{{ competency.title }}</strong>
                        <p>{{ competency.scopeDefinition }}</p>
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
                  v-if="['PROPOSED', 'DRAFT'].includes(messageJob(item)?.changeSetStatus ?? '')"
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
                    {{
                      isClosedAnalysis(item)
                        ? '재오픈 대비 로드맵 미리보기'
                        : messageJob(item)?.analysisProvider === 'UNIFIED'
                          ? '로드맵 미리보기'
                          : '목표 공고에 추가'
                    }}
                    <ArrowRight :size="17" />
                  </button>
                </div>
                <div
                  v-else-if="['APPROVED', 'APPLIED'].includes(messageJob(item)?.changeSetStatus ?? '')"
                  class="analysis-resolution analysis-resolution--applied"
                >
                  <Check :size="17" />
                  목표 목록에 추가되었습니다. 로드맵에서 새 초안을 적용해 주세요.
                </div>
                <div
                  v-else-if="['REJECTED', 'CANCELLED'].includes(messageJob(item)?.changeSetStatus ?? '')"
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
                ['FAILED', 'CANCELLED'].includes(chatJobForMessage(item)?.status ?? '')
              "
              class="inline-ai-status"
              :class="`inline-ai-status--${chatJobForMessage(item)?.status.toLowerCase()}`"
            >
              <template v-if="chatJobForMessage(item)?.status === 'FAILED'">
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
              <template v-else-if="chatJobForMessage(item)?.status === 'CANCELLED'">
                <X :size="17" />
                <span>사용자가 답변 생성을 중단했습니다.</span>
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

        <article
          v-if="activeComposerChatJob"
          class="chat-message chat-message--assistant chat-message--live"
          aria-live="polite"
          aria-label="JOBIS 실시간 작업 상태"
        >
          <div class="chat-bubble chat-bubble--live">
            <AgentExecutionMap
              v-if="
                activeComposerChatJob.result.plan?.agents?.length ||
                activeComposerChatJob.progressEvents.length
              "
              compact
              :plan="activeComposerChatJob.result.plan"
              :events="activeComposerChatJob.progressEvents"
              :status="activeComposerChatJob.status"
            />
            <div v-else class="chat-live-preparing" role="status">
              <Sparkles :size="18" />
              <div>
                <strong>{{ activeComposerChatJob.stageMessage || "요청을 이해하고 있어요" }}</strong>
                <small>필요한 작업과 자료를 확인하고 있습니다.</small>
              </div>
            </div>
          </div>
        </article>
      </div>

      <div
        v-if="activeComposerChatJob && showNewMessages"
        class="chat-floating-status"
      >
        <button
          class="chat-live-follow"
          type="button"
          aria-label="최신 메시지로 이동"
          title="최신 메시지로 이동"
          @click="scrollToBottom()"
        >
          <span class="chat-live-follow__dots" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
        </button>
      </div>

      <footer v-if="conversation?.status === 'ARCHIVED'" class="chat-composer chat-composer--archived">
        <Archive :size="20" />
        <div><strong>보관된 대화입니다</strong><small>메시지를 이어가려면 대화를 먼저 복원해 주세요.</small></div>
        <button class="press-button press-button--secondary" type="button" @click="restoreCurrentConversation"><ArchiveRestore :size="16" /> 대화 복원</button>
      </footer>
      <footer v-else class="chat-composer">
        <p v-if="error" class="form-error">{{ error }}</p>
        <section v-if="showAgentContext" class="agent-context-panel">
          <header>
            <div>
              <p class="eyebrow">ADVANCED AGENT CONTROL</p>
              <h3>필요할 때만 작업과 근거를 직접 지정하세요</h3>
            </div>
            <button
              class="icon-button"
              type="button"
              aria-label="에이전트 설정 닫기"
              @click="showAgentContext = false"
            >
              <X :size="17" />
            </button>
          </header>
          <label class="agent-mode-field">
            작업 모드
            <select v-model="agentMode">
              <option v-for="mode in agentModes" :key="mode.value" :value="mode.value">
                {{ mode.label }}
              </option>
            </select>
            <small>{{ selectedMode.description }}</small>
          </label>

          <div class="agent-asset-columns">
            <section>
              <header>
                <strong>채용 공고</strong>
                <small>{{ selectedPostingIds.length }}/5</small>
              </header>
              <div v-if="assetsLoading" class="agent-asset-empty">
                <LoaderCircle class="spin" :size="16" /> 불러오는 중
              </div>
              <div v-else-if="availablePostings.length" class="agent-asset-list">
                <button
                  v-for="posting in availablePostings"
                  :key="posting.id"
                  type="button"
                  :class="{ selected: selectedPostingIds.includes(posting.id) }"
                  @click="togglePosting(posting.id)"
                >
                  <span><BriefcaseBusiness :size="15" /></span>
                  <strong>{{ postingLabel(posting) }}</strong>
                  <i><Check :size="12" /></i>
                </button>
              </div>
              <RouterLink v-else class="agent-asset-empty" :to="{ name: 'posting-new' }">
                분석한 공고가 없습니다 · 공고 추가
              </RouterLink>
            </section>

            <section>
              <header>
                <strong>커리어 원본 자료</strong>
                <small>{{ selectedCareerSourceIds.length }}/5</small>
              </header>
              <div v-if="assetsLoading" class="agent-asset-empty">
                <LoaderCircle class="spin" :size="16" /> 불러오는 중
              </div>
              <div v-else-if="availableCareerSources.length" class="agent-asset-list">
                <button
                  v-for="source in availableCareerSources"
                  :key="source.id"
                  type="button"
                  :disabled="source.status !== 'CONFIRMED'"
                  :class="{ selected: selectedCareerSourceIds.includes(source.id) }"
                  @click="toggleCareerSource(source.id)"
                >
                  <span><FilePlus2 :size="15" /></span>
                  <strong>{{ source.title }}</strong>
                  <i><Check :size="12" /></i>
                </button>
              </div>
              <RouterLink v-else class="agent-asset-empty" :to="{ name: 'storage', query: { add: '1' } }">
                등록한 자료가 없습니다 · 자료 추가
              </RouterLink>
            </section>
          </div>

          <p
            class="agent-context-requirement"
            :class="{ warning: !contextReady }"
          >
            <Check v-if="contextReady" :size="15" />
            <CircleAlert v-else :size="15" />
            {{
              agentMode === 'AUTO'
                ? "선택하지 않아도 최근 공고와 확정된 커리어 자료에서 필요한 근거를 찾습니다."
                : contextReady
                  ? "이 근거로 작업을 시작할 수 있습니다."
                  : contextRequirementText()
            }}
          </p>
        </section>

        <div class="composer-box">
          <button
            class="composer-posting-analysis composer-posting-analysis--icon"
            type="button"
            :disabled="sending"
            aria-label="공고 분석 시작"
            title="공고 분석 시작"
            @click="startPostingAnalysis"
          >
            <BriefcaseBusiness :size="19" />
          </button>
          <button
            class="composer-attach"
            type="button"
            :disabled="sending"
            aria-label="이력서 파일 첨부 (TXT·MD·DOCX)"
            title="이력서 파일 첨부 (TXT·MD·DOCX)"
            @click="resumeFileInput?.click()"
          >
            <Paperclip :size="18" />
          </button>
          <input
            ref="resumeFileInput"
            type="file"
            style="display: none"
            accept=".docx,.txt,.md,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/markdown"
            @change="attachResumeFile"
          />
          <textarea
            ref="composerInput"
            v-model="message"
            rows="1"
            :placeholder="
              agentMode === 'AUTO'
                ? '무엇이든 물어보세요. JOBIS가 담당자를 선택합니다.'
                : `${selectedMode.label}에게 요청할 내용을 입력하세요.`
            "
            @keydown="onComposerKeydown"
            @input="resizeComposer"
          />
          <button
            class="composer-send"
            :class="{ 'composer-send--stop': activeComposerChatJob }"
            type="button"
            :disabled="activeComposerChatJob ? actionJobId === activeComposerChatJob.id : !message.trim() || sending"
            :aria-label="activeComposerChatJob ? '답변 생성 중단' : '메시지 보내기'"
            :title="activeComposerChatJob ? '답변 생성 중단' : '메시지 보내기'"
            @click="activeComposerChatJob ? cancelChat(activeComposerChatJob) : sendText()"
          >
            <X v-if="activeComposerChatJob" :size="19" :stroke-width="3" />
            <LoaderCircle v-else-if="sending" class="spin" :size="20" />
            <Send v-else :size="20" />
          </button>
        </div>
        <small class="composer-guidance" :class="{ error: composerHasLengthError }">
          {{ composerHint }}
        </small>
        <button
          v-if="!showPosting && (rawText || sourceUrl || attachedV3Source)"
          class="composer-draft-resume"
          type="button"
          @click="openPostingModal"
        >
          작성 중인 공고 확인 계속하기
        </button>
      </footer>
    </section>

    <button
      v-if="showPosting"
      class="modal-backdrop"
      type="button"
      aria-label="공고 첨부 닫기"
      @click="closePostingModal"
    />
    <section
      v-if="showPosting"
      v-dialog-focus="{ onEscape: closePostingModal }"
      class="posting-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="chat-posting-dialog-title"
      tabindex="-1"
    >
      <header>
        <div class="modal-icon"><BriefcaseBusiness :size="22" /></div>
        <div>
          <p class="eyebrow">ATTACH A POSTING</p>
          <h2 id="chat-posting-dialog-title">분석할 채용 공고</h2>
        </div>
        <button class="icon-button" type="button" aria-label="공고 입력 창 닫기" @click="closePostingModal">
          <X :size="20" />
        </button>
      </header>
      <template v-if="!attachedV3Source">
        <div class="source-tabs">
          <button
            type="button"
            :class="{ active: sourceType === 'TEXT' }"
            @click="selectAttachedSourceType('TEXT')"
          >
            공고문 붙여넣기
          </button>
          <button
            type="button"
            :class="{ active: sourceType === 'URL' }"
            @click="selectAttachedSourceType('URL')"
          >
            <Globe2 :size="16" /> URL로 가져오기
          </button>
        </div>
        <label v-if="sourceType === 'URL'">
          공고 상세 페이지 URL
          <input v-model="sourceUrl" type="url" required placeholder="https://…" />
          <small>목록이나 검색 결과가 아닌 공고 상세 페이지 주소를 넣어주세요.</small>
        </label>
        <label v-else>
          공고 원문
          <textarea
            v-model="rawText"
            minlength="20"
            placeholder="회사, 직무, 자격 요건, 우대 사항을 포함한 공고 원문을 붙여넣어 주세요."
          />
          <small :class="{ 'input-length-error': rawText.trim().length > POSTING_TEXT_MAX_CHARS }">
            {{ rawText.length.toLocaleString() }} / {{ POSTING_TEXT_MAX_CHARS.toLocaleString() }}자
          </small>
          <span v-if="rawText.trim().length > POSTING_TEXT_MAX_CHARS" class="input-length-help">
            회사 소개, 복리후생, 채용 절차와 중복 안내를 줄여주세요. 직무·업무·경력·필수·우대사항은 남겨주세요.
          </span>
        </label>
        <button
          class="press-button press-button--primary modal-submit"
          type="button"
          :disabled="sending || !canPrepareAttachedPosting()"
          @click="prepareAttachedPosting"
        >
          <LoaderCircle v-if="sending" class="spin" :size="19" />
          <Sparkles v-else :size="19" />
          {{
            sending
              ? sourceType === 'TEXT'
                ? '직무와 조건을 구조화하고 있어요'
                : '공고를 수집해 에이전트에게 전달하고 있어요'
              : sourceType === 'TEXT'
                ? '직무·경력 확인 시작하기'
                : '에이전트로 공고 정리하기'
          }}
        </button>
      </template>

      <section
        v-else-if="attachedPostingReviewState === 'PENDING'"
        class="posting-source-confirmation posting-source-confirmation--chat"
      >
        <header>
          <span><LoaderCircle class="spin" :size="21" /></span>
          <div>
            <p class="eyebrow">AGENT REVIEW</p>
            <h3>JOBIS가 공고의 직무와 조건을 정리하고 있어요</h3>
            <p>여러 직무나 경력 기준이 발견되면 대화창에서 먼저 질문합니다. 답변이 끝나면 정리한 내용을 이 창에서 확인할 수 있어요.</p>
          </div>
        </header>
        <div class="posting-source-confirmation__actions">
          <button class="press-button press-button--primary" type="button" @click="closePostingModal">
            <MessageCircleMore :size="17" /> 대화에서 진행 상황 보기
          </button>
        </div>
      </section>

      <section v-else class="posting-source-confirmation posting-source-confirmation--chat">
        <header>
          <span><CheckCircle2 :size="21" /></span>
          <div>
            <p class="eyebrow">SOURCE CHECK</p>
            <h3>{{ attachedPostingReviewState === 'READY' ? '에이전트가 정리한 공고 내용을 확인해 주세요' : 'URL에서 가져온 원문을 확인해 주세요' }}</h3>
            <p v-if="attachedPostingReviewState === 'READY'">선택한 직무를 기준으로 담당 업무·경력·필수·우대 조건만 추렸습니다. 필요한 부분을 고친 뒤 분석을 시작해 주세요.</p>
            <p v-else>이 단계는 원문 추출 오류만 고치는 단계입니다. 직무를 선택한 뒤 필요한 내용만 별도 확인합니다.</p>
          </div>
        </header>
        <div v-if="attachedV3Source.sourceDocument.warnings.length" class="posting-source-warnings">
          <strong>확인이 필요한 내용 {{ attachedV3Source.sourceDocument.warnings.length }}개</strong>
          <ul>
            <li v-for="warning in attachedV3Source.sourceDocument.warnings" :key="`${warning.code}:${warning.message}`">
              {{ warning.message }}
            </li>
          </ul>
        </div>
        <label>
          {{ attachedPostingReviewState === 'READY' ? '분석에 사용할 공고 요약' : '분석에 사용할 공고 내용' }}
          <textarea v-model="rawText" rows="12" />
          <small :class="{ 'input-length-error': rawText.trim().length > POSTING_TEXT_MAX_CHARS }">
            {{ rawText.length.toLocaleString() }} / {{ POSTING_TEXT_MAX_CHARS.toLocaleString() }}자 · 수정 내용은 검증 기록으로 남습니다.
          </small>
          <span v-if="rawText.trim().length > POSTING_TEXT_MAX_CHARS" class="input-length-help">
            정리 결과가 비정상적으로 길어요. 다시 입력해 JOBIS가 내용을 재정리하도록 해주세요.
          </span>
        </label>
        <details class="posting-extraction-details">
          <summary>
            {{ attachedPostingReviewState === 'READY' ? '수집 원문 보기' : '추출 근거 보기' }}
            · {{ attachedV3Source.sourceDocument.segments.length }}개
          </summary>
          <ol>
            <li v-for="segment in attachedV3Source.sourceDocument.segments" :key="segment.segmentId">
              <span>{{ segment.method }}</span>
              <p>{{ segment.text }}</p>
            </li>
          </ol>
        </details>
        <div class="posting-source-confirmation__actions">
          <button class="press-button press-button--ghost" type="button" :disabled="sending" @click="resetAttachedSource">
            <RotateCcw :size="17" /> 다시 입력
          </button>
          <button
            class="press-button press-button--primary"
            type="button"
            :disabled="sending || rawText.trim().length < 20 || rawText.trim().length > POSTING_TEXT_MAX_CHARS"
            @click="confirmAttachedPosting"
          >
            <LoaderCircle v-if="sending" class="spin" :size="18" />
            <CheckCircle2 v-else :size="18" />
            {{ sending ? '확인 내용을 저장하고 있어요' : attachedPostingReviewState === 'READY' ? '이 내용으로 분석 시작' : '내용이 맞아요 · 분석 시작' }}
          </button>
        </div>
      </section>
    </section>
  </main>
</template>
