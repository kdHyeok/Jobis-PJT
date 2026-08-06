<script setup lang="ts">
import {
  ArrowLeft,
  ArrowRight,
  BriefcaseBusiness,
  Check,
  ChevronRight,
  CircleAlert,
  Clock3,
  ExternalLink,
  LoaderCircle,
  MoreHorizontal,
  Pencil,
  RefreshCw,
  Sparkles,
  Trash2,
  Archive,
  ArchiveRestore,
  X,
} from "@lucide/vue";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api } from "@/api";
import { productDialog } from "@/product-dialog";
import AnalysisProgressWheel from "@/components/AnalysisProgressWheel.vue";
import V3PostingReviewCard from "@/components/V3PostingReviewCard.vue";
import type {
  AlternativePosting,
  AnalysisJob,
  AnalyzedCompetency,
  AnalyzedRequirement,
  PostingDetail,
  RoadmapCompetency,
  RoadmapWorkspace,
} from "@/types";

const route = useRoute();
const router = useRouter();
const posting = ref<PostingDetail | null>(null);
const job = ref<AnalysisJob | null>(null);
const loading = ref(true);
const actionLoading = ref(false);
const error = ref("");
const selectedAnswer = ref("");
const visibleQuestionId = ref<string | null>(null);
const alternatives = ref<AlternativePosting[]>([]);
const alternativesLoading = ref(false);
const alternativesLoaded = ref(false);
const alternativesError = ref("");
const roadmap = ref<RoadmapWorkspace | null>(null);
const manageOpen = ref(false);
const editOpen = ref(false);
const editSourceUrl = ref("");
const editRawText = ref("");
let pollTimer: number | null = null;
let jobRefreshInFlight = false;

const postingId = computed(() => String(route.params.postingId));
const isV3Analysis = computed(() => job.value?.analysisProvider === "UNIFIED");
const v3Result = computed(() => (isV3Analysis.value ? job.value?.result as any : null));
const v3Assessment = computed(() => v3Result.value?.fit?.assessment ?? null);
const isClosedPosting = computed(() =>
  ["EXPIRED", "CLOSED"].includes(posting.value?.lifecycleStatus ?? ""),
);
const v3PostingReview = computed(() => job.value?.result?.postingReview ?? null);
const v3Position = computed(() => {
  const positions = v3Result.value?.structuredPosting?.positions;
  const selected = v3Result.value?.resolution?.selectedPositionId;
  return Array.isArray(positions)
    ? positions.find((item: any) => item.positionId === selected) ?? positions[0] ?? null
    : null;
});
const v3RequirementAssessment = computed(() => new Map<string, any>(
  (v3Assessment.value?.requirementAssessments ?? []).map(
    (item: any) => [item.requirementId, item],
  ),
));
const v3Requirements = computed(() =>
  Array.isArray(v3Position.value?.requirements) ? v3Position.value.requirements : [],
);
const v3Required = computed(() =>
  v3Requirements.value.filter((item: any) => item.obligation === "REQUIRED"),
);
const v3Preferred = computed(() =>
  v3Requirements.value.filter((item: any) => item.obligation === "PREFERRED"),
);
const v3RoadmapOperations = computed(() => {
  const operations = (job.value?.proposal as any)?.operations;
  return Array.isArray(operations) ? operations : [];
});
const reuseMessage = computed(() =>
  route.query.reused === "1"
    ? String(
        route.query.reuseMessage ??
          "같은 공고의 기존 분석을 재사용해 현재 준비도만 다시 계산합니다.",
      )
    : "",
);
const competencyByRef = computed(
  () =>
    new Map(
      (job.value?.proposal?.competencies ?? []).map(
        (competency) => [competency.ref, competency] as const,
      ),
    ),
);
const roadmapCompetencies = computed(() =>
  (job.value?.proposal?.competencies ?? []).filter(
    (competency) => competency.roadmapEligible !== false,
  ),
);
const experienceCompetencies = computed(() =>
  (job.value?.proposal?.competencies ?? []).filter(
    (competency) =>
      competency.roadmapEligible === false && competency.kind === "EXPERIENCE",
  ),
);
const qualitativeCompetencies = computed(() =>
  (job.value?.proposal?.competencies ?? []).filter(
    (competency) =>
      competency.roadmapEligible === false && competency.kind !== "EXPERIENCE",
  ),
);
function uniqueRequirements(items: AnalyzedRequirement[]) {
  const seen = new Set<string>();
  return items.filter((requirement) => {
    const key = `${requirement.competencyRef}:${requirement.sourceText.trim()}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
const required = computed(() =>
  uniqueRequirements((job.value?.proposal?.requirements ?? []).filter(
    (requirement) =>
      requirement.relation === "REQUIRED" &&
      competencyByRef.value.get(requirement.competencyRef)?.roadmapEligible !== false,
  )),
);
const preferred = computed(() =>
  uniqueRequirements((job.value?.proposal?.requirements ?? []).filter(
    (requirement) =>
      requirement.relation === "PREFERRED" &&
      competencyByRef.value.get(requirement.competencyRef)?.roadmapEligible !== false,
  )),
);
const responsibilities = computed(() =>
  uniqueRequirements((job.value?.proposal?.requirements ?? []).filter(
    (requirement) => requirement.relation === "RESPONSIBILITY",
  )),
);
const currentCompetencies = computed(() => {
  const result = new Map<string, RoadmapCompetency>();
  for (const node of roadmap.value?.current.nodes ?? []) {
    for (const competency of node.competencies) {
      const previous = result.get(competency.canonicalKey);
      if (!previous || competency.verifiedLevel > previous.verifiedLevel) {
        result.set(competency.canonicalKey, competency);
      }
    }
  }
  return result;
});

function verdictLabel(value?: string) {
  if (value === "REVIEW_REQUIRED") return "판정 보류";
  if (value === "APPLY_NOW") return "지금 지원";
  if (value === "STRENGTHEN_THEN_APPLY") return "보강 후 지원";
  if (value === "ALTERNATIVE_FIRST") return "대체 공고 우선";
  if (value === "ALTERNATIVE_PATH") return "대체 경로 우선";
  if (value === "UNKNOWN") return "판정 보류";
  return "분석 결과";
}

function readinessValue(value: unknown, emptyLabel = "근거 없음") {
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
    return "확정된 커리어 자료가 없어 공고 조건만으로 로드맵을 만들었습니다.";
  }
  return "";
}

function v3RequirementStatusLabel(requirementId: string) {
  const status = v3RequirementAssessment.value.get(requirementId)?.status;
  return ({
    VERIFIED_MET: "검증 완료",
    EVIDENCED: "근거 있음",
    CLAIMED_ONLY: "본인 확인",
    PARTIAL: "일부 충족",
    NOT_MET: "보완 필요",
    UNKNOWN: "정보 부족",
    NOT_APPLICABLE: "판정 제외",
  } as Record<string, string>)[status] ?? "확인 필요";
}

function v3RequirementStatusClass(requirementId: string) {
  const status = v3RequirementAssessment.value.get(requirementId)?.status;
  if (status === "VERIFIED_MET") return "met";
  if (["EVIDENCED", "CLAIMED_ONLY", "PARTIAL"].includes(status)) return "gap";
  return "missing";
}

function competencyTitle(ref: string) {
  return competencyByRef.value.get(ref)?.title ?? ref;
}

function competencyStatus(competency: AnalyzedCompetency | undefined) {
  if (!competency) return "현재 역량을 확인할 수 없습니다.";
  const current = currentCompetencies.value.get(competency.canonicalKey);
  if (!current) return `요구 수준 ${competency.requiredLevel} · 아직 검증 기록 없음`;
  const gap = Math.max(0, competency.requiredLevel - current.verifiedLevel);
  if (!gap && current.progressStatus === "COMPLETED") {
    return `요구 수준 ${competency.requiredLevel} · 검증 수준 ${current.verifiedLevel} · 충족`;
  }
  return `요구 수준 ${competency.requiredLevel} · 검증 수준 ${current.verifiedLevel} · ${gap ? `${gap}단계 보완 필요` : "완료 확인 필요"}`;
}

function competencyProgressClass(ref: string) {
  const analyzed = competencyByRef.value.get(ref);
  if (!analyzed) return "unknown";
  const current = currentCompetencies.value.get(analyzed.canonicalKey);
  if (!current) return "missing";
  return current.progressStatus === "COMPLETED" && current.verifiedLevel >= analyzed.requiredLevel
    ? "met"
    : "gap";
}

async function refreshAnalysisJob(scheduleAfter = true) {
  const analysisJobId = posting.value?.analysisJobId;
  if (!analysisJobId || jobRefreshInFlight) return;
  jobRefreshInFlight = true;
  try {
    const refreshed = await api.analysisJob(analysisJobId);
    job.value = refreshed;
    if (refreshed.pendingQuestion?.id !== visibleQuestionId.value) {
      visibleQuestionId.value = refreshed.pendingQuestion?.id ?? null;
      selectedAnswer.value = "";
    }
    if (refreshed.status === "SUCCEEDED" && !alternativesLoaded.value) {
      void loadAlternatives();
    }
  } catch (cause) {
    error.value = cause instanceof Error
      ? cause.message
      : "분석 상태를 다시 불러오지 못했습니다.";
  } finally {
    jobRefreshInFlight = false;
    if (scheduleAfter) schedulePoll();
  }
}

async function load() {
  error.value = "";
  try {
    const [postingResult, roadmapResult] = await Promise.allSettled([
      api.posting(postingId.value),
      api.roadmap(),
    ] as const);
    if (postingResult.status === "rejected") throw postingResult.reason;
    posting.value = postingResult.value;
    if (roadmapResult.status === "fulfilled") roadmap.value = roadmapResult.value;
    if (posting.value.analysisJobId) await refreshAnalysisJob(false);
    else job.value = null;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "공고를 불러오지 못했습니다.";
  } finally {
    loading.value = false;
    schedulePoll();
  }
}

async function loadAlternatives() {
  alternativesLoading.value = true;
  alternativesError.value = "";
  try {
    alternatives.value = await api.alternativePostings(postingId.value);
    alternativesLoaded.value = true;
  } catch (cause) {
    alternatives.value = [];
    alternativesError.value = cause instanceof Error ? cause.message : "대체 공고를 불러오지 못했습니다.";
  } finally {
    alternativesLoading.value = false;
  }
}

function startEdit() {
  if (!posting.value) return;
  editSourceUrl.value = posting.value.sourceUrl ?? "";
  editRawText.value = posting.value.rawText;
  editOpen.value = true;
  manageOpen.value = false;
}

async function savePosting() {
  if (!posting.value || editRawText.value.trim().length < 20) return;
  actionLoading.value = true;
  error.value = "";
  try {
    await api.updatePosting(posting.value.id, editSourceUrl.value.trim() || null, editRawText.value.trim());
    editOpen.value = false;
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "공고를 수정하지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

async function toggleArchive() {
  if (!posting.value) return;
  actionLoading.value = true;
  try {
    if (posting.value.archivedAt) await api.restorePosting(posting.value.id);
    else await api.archivePosting(posting.value.id);
    manageOpen.value = false;
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "공고 상태를 변경하지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

async function deletePosting() {
  if (!posting.value || !await productDialog.confirm({ title: "채용 공고 영구 삭제", message: "이 공고와 연결된 분석 기록을 영구 삭제할까요? 이 작업은 되돌릴 수 없습니다.", confirmLabel: "영구 삭제", danger: true })) return;
  actionLoading.value = true;
  try {
    await api.deletePosting(posting.value.id);
    await router.replace({ name: "postings" });
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "공고를 삭제하지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

function schedulePoll() {
  if (pollTimer) window.clearTimeout(pollTimer);
  if (!job.value || !["QUEUED", "RUNNING"].includes(job.value.status)) return;
  pollTimer = window.setTimeout(() => void refreshAnalysisJob(), 2500);
}

async function retry() {
  if (!job.value) return;
  actionLoading.value = true;
  try {
    await api.retryAnalysis(job.value.id);
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "분석을 재시도하지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

async function cancelAnalysis() {
  if (
    !job.value ||
    !await productDialog.confirm({ title: "공고 분석 중단", message: "진행 중인 분석을 취소할까요? 공고와 지금까지 입력한 답변은 그대로 보관됩니다.", confirmLabel: "분석 중단", danger: true })
  ) return;
  actionLoading.value = true;
  error.value = "";
  try {
    await api.cancelAnalysis(job.value.id);
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "분석을 취소하지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

async function answerQuestion(
  answerStatus: "PROVIDED" | "CONFIRMED_ABSENT" = "PROVIDED",
) {
  const currentJob = job.value;
  const question = currentJob?.pendingQuestion;
  if (!currentJob || !question) return;
  if (answerStatus === "CONFIRMED_ABSENT") {
    selectedAnswer.value = "없습니다.";
  }
  if (!selectedAnswer.value) return;
  actionLoading.value = true;
  error.value = "";
  try {
    await api.answerAnalysisQuestion(
      currentJob.id,
      question.id,
      selectedAnswer.value,
      answerStatus,
    );
    await load();
  } catch (cause) {
    error.value =
      cause instanceof Error ? cause.message : "답변을 반영하지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

async function confirmPostingReview() {
  if (!job.value?.pendingQuestion) return;
  selectedAnswer.value = "CONFIRM";
  await answerQuestion("PROVIDED");
}

async function approve() {
  if (!job.value) return;
  actionLoading.value = true;
  try {
    if (job.value.analysisProvider === "UNIFIED") {
      if (!job.value.changeSetId) throw new Error("로드맵 초안을 찾을 수 없습니다.");
      await api.previewV3Roadmap(job.value.changeSetId);
      await router.push({
        name: "map",
        query: { provider: "unified", proposal: job.value.changeSetId, preview: "draft" },
      });
      return;
    }
    await api.approveAnalysis(job.value.id);
    await router.push({
      name: "map",
      query: { posting: postingId.value, preview: "draft" },
    });
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "목표 공고에 추가하지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

async function reject() {
  if (!job.value || !await productDialog.confirm({ title: "변경안 거절", message: "이 지도 변경안을 반영하지 않을까요? 공고 분석 기록은 유지됩니다.", confirmLabel: "변경안 거절", danger: true })) return;
  actionLoading.value = true;
  try {
    if (job.value.analysisProvider === "UNIFIED") {
      if (!job.value.changeSetId) throw new Error("로드맵 초안을 찾을 수 없습니다.");
      await api.cancelV3Roadmap(job.value.changeSetId);
      await load();
      return;
    }
    await api.rejectAnalysis(job.value.id);
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "변경안을 거절하지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

function refreshOnReturn() {
  if (document.visibilityState === "visible") void refreshAnalysisJob();
}

onMounted(() => {
  void load();
  window.addEventListener("focus", refreshOnReturn);
  document.addEventListener("visibilitychange", refreshOnReturn);
});
onBeforeUnmount(() => {
  if (pollTimer) window.clearTimeout(pollTimer);
  window.removeEventListener("focus", refreshOnReturn);
  document.removeEventListener("visibilitychange", refreshOnReturn);
});
</script>

<template>
  <main class="workspace posting-detail-workspace">
    <RouterLink class="back-link" :to="{ name: 'postings' }">
      <ArrowLeft :size="17" /> 채용 공고
    </RouterLink>
    <div v-if="loading" class="state-panel">
      <LoaderCircle class="spin" :size="24" /> 공고와 분석 결과를 불러오는 중입니다.
    </div>
    <template v-else-if="posting">
      <section v-if="reuseMessage" class="posting-reuse-notice">
        <RefreshCw :size="18" />
        <div>
          <strong>기존 공고 분석을 재사용합니다</strong>
          <p>{{ reuseMessage }}</p>
        </div>
      </section>
      <section class="posting-detail-hero">
        <div class="posting-company-mark">
          {{ posting.companyName?.slice(0, 1) ?? "?" }}
        </div>
        <div>
          <p class="eyebrow">{{ posting.companyName ?? "분석 중인 공고" }}</p>
          <h1>{{ posting.roleTitle ?? "직무 정보를 분석하고 있어요" }}</h1>
          <p>
            {{ posting.experienceText ?? "경력 조건 확인 중" }}
            <template v-if="posting.employmentType"> · {{ posting.employmentType }}</template>
          </p>
          <span
            v-if="['EXPIRED', 'CLOSED'].includes(posting.lifecycleStatus ?? '')"
            class="posting-lifecycle posting-lifecycle--closed"
          >
            모집 마감 · 재오픈 대비
          </span>
        </div>
        <div class="posting-detail-hero__actions">
          <a
            v-if="posting.sourceUrl"
            class="press-button press-button--ghost"
            :href="posting.sourceUrl"
            target="_blank"
            rel="noopener noreferrer"
          >
            원본 공고 <ExternalLink :size="16" />
          </a>
          <RouterLink
            class="press-button press-button--secondary"
            :to="{
              name: 'chat',
              query: { mode: 'POSTING_QA', posting: posting.id },
            }"
          >
            <Sparkles :size="16" /> 이 공고로 AI와 대화
          </RouterLink>
          <div class="posting-manage-menu">
            <button class="icon-button" type="button" aria-label="공고 관리" :aria-expanded="manageOpen" @click="manageOpen = !manageOpen">
              <MoreHorizontal :size="19" />
            </button>
            <div v-if="manageOpen" class="posting-manage-menu__popover">
              <button type="button" @click="startEdit"><Pencil :size="15" /> 원문 수정</button>
              <button type="button" @click="toggleArchive">
                <ArchiveRestore v-if="posting.archivedAt" :size="15" /><Archive v-else :size="15" />
                {{ posting.archivedAt ? '보관 해제' : '보관하기' }}
              </button>
              <button class="danger" type="button" @click="deletePosting"><Trash2 :size="15" /> 영구 삭제</button>
            </div>
          </div>
        </div>
      </section>

      <section v-if="editOpen" class="posting-edit-panel">
        <header><div><p class="eyebrow">EDIT POSTING</p><h2>공고 원문 수정</h2></div><button class="icon-button" type="button" aria-label="닫기" @click="editOpen = false"><X :size="18" /></button></header>
        <label>원문 URL<input v-model="editSourceUrl" type="url" placeholder="https://" /></label>
        <label>공고 원문<textarea v-model="editRawText" rows="12" maxlength="60000" /></label>
        <small>수정하면 새 분석 작업이 시작되며 기존 적용 지도는 사용자가 다시 승인하기 전까지 유지됩니다.</small>
        <button class="press-button press-button--primary" type="button" :disabled="actionLoading || editRawText.trim().length < 20" @click="savePosting">
          <Check :size="17" /> 저장하고 다시 분석
        </button>
      </section>

      <p v-if="error" class="form-error">{{ error }}</p>
      <p
        v-if="['EXPIRED', 'CLOSED'].includes(posting.lifecycleStatus ?? '')"
        class="posting-closed-notice"
      >
        모집은 마감되었지만 다음 채용을 대비하는 준비 목표로 등록할 수 있습니다.
        실제 재공고에서는 조건이 달라질 수 있으므로 공고가 다시 열리면 새 분석으로 갱신해 주세요.
      </p>

      <details
        v-if="job?.questionHistory?.length && job.status !== 'WAITING_FOR_INPUT'"
        class="analysis-question-history analysis-question-history--persistent"
        open
      >
        <summary>분석 과정에서 확인한 내용 {{ job.questionHistory.length }}개</summary>
        <ol>
          <li v-for="item in job.questionHistory" :key="item.id">
            <strong>{{ item.text }}</strong>
            <span>{{ item.answerValue }}</span>
          </li>
        </ol>
      </details>

      <details
        v-if="job?.status === 'SUCCEEDED' && job.progressEvents?.length"
        class="analysis-completed-timeline"
      >
        <summary>완료된 분석 진행 과정 보기</summary>
        <AnalysisProgressWheel
          compact
          status="SUCCEEDED"
          :stage="job.stage"
          :stage-message="job.stageMessage"
          :queue-position="job.queuePosition"
          :events="job.progressEvents"
        />
      </details>

      <section
        v-if="job && ['QUEUED', 'RUNNING'].includes(job.status)"
        class="analysis-progress-panel"
      >
        <AnalysisProgressWheel
          :status="job.status"
          :stage="job.stage"
          :stage-message="job.stageMessage"
          :queue-position="job.queuePosition"
          :events="job.progressEvents"
        />
        <p class="analysis-progress-note">
          이 페이지를 나가도 작업은 계속되며 완료되면 알림으로 알려드립니다.
        </p>
        <div class="analysis-progress-actions">
          <button
            class="press-button press-button--ghost"
            type="button"
            :disabled="actionLoading"
            @click="cancelAnalysis"
          >
            <LoaderCircle v-if="actionLoading" class="spin" :size="17" />
            <X v-else :size="17" />
            분석 취소
          </button>
        </div>
      </section>

      <section
        v-else-if="job?.status === 'WAITING_FOR_INPUT' && job.pendingQuestion"
        class="analysis-question-panel"
      >
        <AnalysisProgressWheel
          compact
          :status="job.status"
          :stage="job.stage"
          :stage-message="job.stageMessage"
          :queue-position="job.queuePosition"
          :events="job.progressEvents"
        />
        <V3PostingReviewCard
          v-if="job.stage === 'AWAITING_POSTING_CONFIRMATION' && v3PostingReview"
          :review="v3PostingReview"
          :busy="actionLoading"
          @confirm="confirmPostingReview"
          @cancel="cancelAnalysis"
        />
        <div v-else class="analysis-question-panel__body">
          <details
            v-if="job.questionHistory?.length"
            class="analysis-question-history"
          >
            <summary>이전 확인 답변 {{ job.questionHistory?.length ?? 0 }}개</summary>
            <ol>
              <li v-for="item in job.questionHistory ?? []" :key="item.id">
                <strong>{{ item.text }}</strong>
                <span>{{ item.answerValue }}</span>
              </li>
            </ol>
          </details>
          <p class="eyebrow">
            QUICK CHECK · {{ job.pendingQuestion.ordinal }}번째 확인
          </p>
          <h2>{{ job.pendingQuestion.text }}</h2>
          <p>{{ job.pendingQuestion.reason }}</p>
          <textarea
            v-if="job.pendingQuestion.inputType === 'TEXT'"
            v-model="selectedAnswer"
            class="analysis-question-text"
            rows="5"
            maxlength="2000"
            placeholder="프로젝트, 맡은 역할, 사용 기술과 결과를 구체적으로 적어주세요."
          />
          <small
            v-if="job.pendingQuestion.inputType === 'TEXT'"
            class="analysis-question-count"
          >
            {{ selectedAnswer.length }}/2,000
          </small>
          <button
            v-if="
              job.pendingQuestion.inputType === 'TEXT' &&
              job.pendingQuestion.absenceScope !== 'NONE'
            "
            class="analysis-question-absence"
            type="button"
            :disabled="actionLoading"
            @click="answerQuestion('CONFIRMED_ABSENT')"
          >
            해당 경험 없음
          </button>
          <div v-else class="analysis-question-options">
            <button
              v-for="option in job.pendingQuestion.options"
              :key="option.value"
              type="button"
              :class="{ selected: selectedAnswer === option.value }"
              @click="selectedAnswer = option.value"
            >
              <span>
                <strong>{{ option.label }}</strong>
                <small>{{ option.description }}</small>
              </span>
              <i><Check :size="15" /></i>
            </button>
          </div>
          <button
            class="press-button press-button--primary"
            type="button"
            :disabled="!selectedAnswer || actionLoading"
            @click="answerQuestion('PROVIDED')"
          >
            <LoaderCircle v-if="actionLoading" class="spin" :size="18" />
            <Check v-else :size="18" />
            이 답변으로 분석 계속하기
          </button>
          <small class="analysis-question-note">
            답변을 반영한 뒤 같은 분석 작업을 백그라운드에서 이어갑니다.
          </small>
          <button
            class="press-button press-button--ghost"
            type="button"
            :disabled="actionLoading"
            @click="cancelAnalysis"
          >
            <X :size="17" /> 분석 취소
          </button>
        </div>
      </section>

      <section
        v-else-if="job?.status === 'CANCELLED'"
        class="analysis-progress-panel analysis-progress-panel--cancelled"
      >
        <span><X :size="24" /></span>
        <div>
          <p class="eyebrow">분석 취소됨</p>
          <h2>진행 중이던 분석을 취소했어요</h2>
          <p>공고와 입력한 답변은 보관되어 있습니다. 필요하면 다시 시작할 수 있어요.</p>
          <button
            class="press-button press-button--secondary"
            type="button"
            :disabled="actionLoading || job.attemptCount >= 3"
            @click="retry"
          >
            <RefreshCw :size="17" /> 다시 분석
          </button>
        </div>
      </section>

      <section v-else-if="job?.status === 'FAILED'" class="analysis-progress-panel analysis-progress-panel--error">
        <span><CircleAlert :size="24" /></span>
        <div>
          <p class="eyebrow">분석 중단</p>
          <h2>커리어 적합도 분석을 마치지 못했어요</h2>
          <p>공고는 안전하게 저장되어 있어요. 같은 공고로 다시 분석할 수 있습니다.</p>
          <details v-if="job.errorMessage" class="analysis-error-details">
            <summary>오류 자세히 보기</summary>
            <p>{{ job.errorMessage }}</p>
          </details>
          <button
            class="press-button press-button--secondary"
            type="button"
            :disabled="actionLoading || job.attemptCount >= 3"
            @click="retry"
          >
            <RefreshCw :size="17" /> 다시 분석
          </button>
        </div>
      </section>

      <template v-else-if="job?.status === 'SUCCEEDED'">
        <template v-if="isV3Analysis">
          <section class="evaluation-banner evaluation-banner--v3">
            <div>
              <p class="eyebrow">VERIFIED FIT ASSESSMENT</p>
              <span>{{ verdictLabel(v3Assessment?.verdictProposal) }}</span>
              <h2>
                <template v-if="v3Assessment?.formalEligibility === 'VERIFIED_MET'">
                  확인된 근거 기준으로 필수 지원 자격을 충족합니다.
                </template>
                <template v-else-if="v3Assessment?.formalEligibility === 'UNKNOWN'">
                  아직 확인할 정보가 남아 있어 지원 자격 판정을 보류합니다.
                </template>
                <template v-else>
                  필수 조건을 보완한 뒤 지원하는 경로를 권장합니다.
                </template>
              </h2>
            </div>
            <Sparkles :size="30" />
          </section>

          <section class="posting-result-grid">
            <article class="proposal-summary-card proposal-summary-card--v3">
              <header><h2>근거 수준별 준비도</h2></header>
              <div>
                <span><strong>{{ readinessValue(v3Assessment?.metrics?.claimedReadinessPercent) }}</strong> 주장 준비도</span>
                <span v-if="v3Assessment?.metrics?.capabilityReadinessPercent != null"><strong>{{ readinessValue(v3Assessment?.metrics?.capabilityReadinessPercent) }}</strong> 필수 역량 준비도</span>
                <span><strong>{{ readinessValue(v3Assessment?.metrics?.evidencedReadinessPercent, '제출 근거 없음') }}</strong> 증거 준비도</span>
                <span><strong>{{ readinessValue(v3Assessment?.metrics?.verifiedReadinessPercent, '검증 자료 없음') }}</strong> 검증 준비도</span>
                <span><strong>{{ requiredVerificationValue(v3Assessment) }}</strong> 검증된 필수 조건</span>
              </div>
            </article>
            <article class="evaluation-reasons">
              <header><h2>강점과 보완점</h2></header>
              <ul>
                <li v-for="item in v3Assessment?.strengths ?? []" :key="`strength:${item}`">
                  <Check :size="17" /><span>{{ item }}</span>
                </li>
                <li v-for="item in v3Assessment?.gaps ?? []" :key="`gap:${item}`" class="is-gap">
                  <CircleAlert :size="17" /><span>{{ item }}</span>
                </li>
              </ul>
            </article>
          </section>
          <p
            v-if="readinessUnavailableMessage(v3Assessment)"
            class="posting-evidence-empty-notice"
          >
            {{ readinessUnavailableMessage(v3Assessment) }}
            <RouterLink :to="{ name: 'storage' }">커리어 자료를 등록하면 준비도를 다시 계산할 수 있어요.</RouterLink>
          </p>

          <section class="requirement-matrix requirement-matrix--v3">
            <header>
              <div>
                <p class="eyebrow">ATOMIC REQUIREMENTS</p>
                <h2>공고 원문 조건과 내 근거 비교</h2>
                <p>주장, 제출 근거, 통과한 검증을 서로 구분해 판정했습니다.</p>
              </div>
            </header>
            <div class="requirement-columns">
              <article>
                <h3>필수 조건</h3>
                <div
                  v-for="requirement in v3Required"
                  :key="requirement.requirementId"
                  class="requirement-detail-row"
                  :class="`requirement-detail-row--${v3RequirementStatusClass(requirement.requirementId)}`"
                >
                  <span class="requirement-pill requirement-pill--required">필수</span>
                  <div>
                    <strong>{{ requirement.atomicText }}</strong>
                    <p>{{ requirement.sourceText }}</p>
                    <small>{{ v3RequirementStatusLabel(requirement.requirementId) }} · 신뢰도 {{ Math.round((requirement.confidence ?? 0) * 100) }}%</small>
                  </div>
                </div>
                <p v-if="!v3Required.length" class="notification-empty">확정된 필수 조건이 없습니다.</p>
              </article>
              <article>
                <h3>우대 조건</h3>
                <div
                  v-for="requirement in v3Preferred"
                  :key="requirement.requirementId"
                  class="requirement-detail-row"
                  :class="`requirement-detail-row--${v3RequirementStatusClass(requirement.requirementId)}`"
                >
                  <span class="requirement-pill requirement-pill--preferred">우대</span>
                  <div>
                    <strong>{{ requirement.atomicText }}</strong>
                    <p>{{ requirement.sourceText }}</p>
                    <small>{{ v3RequirementStatusLabel(requirement.requirementId) }} · 신뢰도 {{ Math.round((requirement.confidence ?? 0) * 100) }}%</small>
                  </div>
                </div>
                <p v-if="!v3Preferred.length" class="notification-empty">확정된 우대 조건이 없습니다.</p>
              </article>
            </div>
          </section>

          <section class="proposal-path-preview proposal-path-preview--v3">
            <header>
              <div>
                <p class="eyebrow">DRAFT OPERATIONS</p>
                <h2>로드맵에 제안된 변화</h2>
                <p>아직 현재 지도에는 반영되지 않았습니다. 미리보기에서 전체 연결을 확인할 수 있어요.</p>
              </div>
            </header>
            <div class="proposal-node-list">
              <article v-for="operation in v3RoadmapOperations" :key="operation.operationId">
                <span class="proposal-action" :class="{ 'proposal-action--create': operation.action !== 'REUSE_NODE' }">
                  {{ operation.action === 'REUSE_NODE' ? '유지' : '추가' }}
                </span>
                <div>
                  <strong>{{ operation.title ?? operation.canonicalKey ?? operation.targetRef }}</strong>
                  <p>{{ operation.scopeDefinition ?? operation.reason }}</p>
                  <small>{{ operation.nodeKind }} · {{ operation.sectionKey }}</small>
                </div>
                <ArrowRight :size="17" />
              </article>
            </div>
          </section>

          <section v-if="job.changeSetStatus === 'DRAFT'" class="proposal-decision-bar">
            <div>
              <Clock3 :size="20" />
              <span>
                <strong>새 로드맵 초안이 준비됐습니다</strong>
                <small>현재 지도는 그대로입니다. 다음 화면에서 미리보기 후 적용하거나 취소할 수 있어요.</small>
              </span>
            </div>
            <button class="press-button press-button--ghost" type="button" :disabled="actionLoading" @click="reject">
              <X :size="17" /> 초안 취소
            </button>
            <button
              class="press-button press-button--primary"
              type="button"
              :disabled="actionLoading || !job.changeSetId"
              @click="approve"
            >
              <Check :size="18" />
              {{ isClosedPosting ? '재오픈 대비 로드맵 미리보기' : '로드맵 미리보기' }}
            </button>
          </section>
          <section v-else-if="job.changeSetStatus === 'APPLIED'" class="analysis-resolution analysis-resolution--applied">
            <Check :size="18" /> 확인한 로드맵 버전에 반영했습니다.
            <RouterLink class="text-action" :to="{ name: 'map' }">
              지도에서 보기 <ArrowRight :size="14" />
            </RouterLink>
          </section>
          <section v-else class="analysis-resolution">이 로드맵 초안은 취소되었습니다.</section>
        </template>

        <template v-else>
        <section class="evaluation-banner">
          <div>
            <p class="eyebrow">JOBIS EVALUATION</p>
            <span>{{ verdictLabel(job.result?.evaluation?.verdict) }}</span>
            <h2>{{ job.result?.evaluation?.summary }}</h2>
          </div>
          <Sparkles :size="30" />
        </section>

        <section class="posting-result-grid">
          <article class="evaluation-reasons">
            <header>
              <h2>판단 근거</h2>
            </header>
            <ul>
              <li
                v-for="reason in job.result?.evaluation?.reasons ?? []"
                :key="reason"
              >
                <Check :size="17" /> <span>{{ reason }}</span>
              </li>
            </ul>
          </article>

          <article class="proposal-summary-card">
            <header>
              <h2>분석 데이터 요약</h2>
            </header>
            <div>
              <span><strong>{{ job.proposal?.competencies.length ?? 0 }}</strong> 정규화된 역량</span>
              <span><strong>{{ required.length }}</strong> 필수 조건</span>
              <span><strong>{{ preferred.length }}</strong> 우대 조건</span>
              <span><strong>{{ responsibilities.length }}</strong> 주요 업무</span>
            </div>
          </article>
        </section>

        <section
          v-if="
            job.result?.evaluation?.verdict === 'ALTERNATIVE_FIRST' ||
            alternatives.length
          "
          class="alternative-postings-panel"
        >
          <header>
            <div>
              <p class="eyebrow">REAL ALTERNATIVES</p>
              <h2>지금 도전하기 가까운 실제 공고</h2>
              <p>
                서비스에 분석된 활성 공고 중 같은 직무와 검증된 역량을
                기준으로 계산했습니다.
              </p>
            </div>
            <button
              class="press-button press-button--ghost"
              type="button"
              :disabled="alternativesLoading"
              @click="loadAlternatives"
            >
              <RefreshCw :size="16" /> 추천 새로고침
            </button>
          </header>
          <div v-if="alternativesLoading" class="notification-empty">
            <LoaderCircle class="spin" :size="20" /> 실제 공고를 비교하고 있어요.
          </div>
          <div v-else-if="alternatives.length" class="alternative-posting-list">
            <article v-for="item in alternatives" :key="item.id">
              <div class="alternative-score">
                <strong>{{ item.matchScore }}</strong>
                <small>적합도</small>
              </div>
              <div>
                <span>{{ item.companyName }}</span>
                <h3>{{ item.roleTitle }}</h3>
                <p>{{ item.reason }}</p>
                <small>
                  필수 {{ item.matchedRequired }}/{{ item.required }} · 우대
                  {{ item.matchedPreferred }}/{{ item.preferred }}
                  <template v-if="item.experienceText">
                    · {{ item.experienceText }}
                  </template>
                </small>
                <p v-if="item.gaps.length" class="alternative-gaps">
                  보완: {{ item.gaps.join(", ") }}
                </p>
              </div>
              <a
                v-if="item.sourceUrl"
                class="icon-button"
                :href="item.sourceUrl"
                target="_blank"
                rel="noopener noreferrer"
                aria-label="대체 공고 원문 열기"
              >
                <ExternalLink :size="18" />
              </a>
            </article>
          </div>
          <div v-else-if="alternativesError" class="inline-error">
            {{ alternativesError }}
            <button class="text-action" type="button" @click="loadAlternatives">다시 불러오기</button>
          </div>
          <p v-else class="notification-empty">
            아직 비교할 수 있는 같은 직무의 다른 활성 공고가 없습니다.
            공고가 더 분석되면 이곳에 실제 후보가 나타납니다.
          </p>
        </section>

        <section class="requirement-matrix">
          <header>
            <div>
              <p class="eyebrow">REQUIREMENT MATRIX</p>
              <h2>공고 조건과 내 커리어 연결</h2>
            </div>
          </header>
          <div class="requirement-columns">
            <article>
              <h3>필수 조건</h3>
              <div
                v-for="requirement in required"
                :key="`${requirement.competencyRef}-required`"
                class="requirement-detail-row"
                :class="`requirement-detail-row--${competencyProgressClass(requirement.competencyRef)}`"
              >
                <span class="requirement-pill requirement-pill--required">필수</span>
                <div>
                  <strong>{{ competencyTitle(requirement.competencyRef) }}</strong>
                  <p>{{ requirement.sourceText }}</p>
                  <small>{{ competencyStatus(competencyByRef.get(requirement.competencyRef)) }}</small>
                </div>
                <ChevronRight :size="17" />
              </div>
              <p v-if="!required.length" class="notification-empty">
                분리된 필수 조건이 없습니다.
              </p>
            </article>
            <article>
              <h3>우대 조건</h3>
              <div
                v-for="requirement in preferred"
                :key="`${requirement.competencyRef}-preferred`"
                class="requirement-detail-row"
                :class="`requirement-detail-row--${competencyProgressClass(requirement.competencyRef)}`"
              >
                <span class="requirement-pill requirement-pill--preferred">우대</span>
                <div>
                  <strong>{{ competencyTitle(requirement.competencyRef) }}</strong>
                  <p>{{ requirement.sourceText }}</p>
                  <small>{{ competencyStatus(competencyByRef.get(requirement.competencyRef)) }}</small>
                </div>
                <ChevronRight :size="17" />
              </div>
              <p v-if="!preferred.length" class="notification-empty">
                분리된 우대 조건이 없습니다.
              </p>
            </article>
          </div>
        </section>

        <section v-if="responsibilities.length" class="proposal-path-preview responsibilities-panel">
          <header><div><p class="eyebrow">ROLE RESPONSIBILITIES</p><h2>입사 후 맡게 될 주요 업무</h2></div></header>
          <ul>
            <li v-for="item in responsibilities" :key="`${item.competencyRef}:${item.sourceText}`">
              <BriefcaseBusiness :size="16" /><span>{{ item.sourceText }}</span>
            </li>
          </ul>
        </section>

        <section class="proposal-path-preview">
          <header>
            <div>
              <p class="eyebrow">COMPETENCY DATA</p>
              <h2>로드맵 제작에 사용할 역량</h2>
            </div>
          </header>
          <div class="proposal-node-list">
            <article
              v-for="competency in roadmapCompetencies"
              :key="competency.ref"
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
              <ArrowRight :size="17" />
            </article>
          </div>
        </section>

        <section
          v-if="experienceCompetencies.length"
          class="proposal-path-preview experience-condition-panel"
        >
          <header>
            <div>
              <p class="eyebrow">EXPERIENCE GATES</p>
              <h2>경력·수행 경험 조건</h2>
            </div>
          </header>
          <p>
            학습 완료로 대체되는 기술 노드가 아니라, 실제 프로젝트·업무 수행 이력으로 충족해야 하는 지원 조건입니다.
          </p>
          <div class="proposal-node-list">
            <article
              v-for="competency in experienceCompetencies"
              :key="competency.ref"
            >
              <span class="proposal-action">조건</span>
              <div>
                <strong>{{ competency.title }}</strong>
                <p>{{ competency.scopeDefinition }}</p>
              </div>
            </article>
          </div>
        </section>

        <section
          v-if="qualitativeCompetencies.length"
          class="proposal-path-preview qualitative-condition-panel"
        >
          <header>
            <div>
              <p class="eyebrow">QUALITATIVE CONDITIONS</p>
              <h2>정성적 채용 조건</h2>
            </div>
          </header>
          <p>
            태도와 조직 적합성에 관한 참고 조건입니다. 로드맵 단계와 준비도
            계산에는 포함하지 않습니다.
          </p>
          <div class="proposal-node-list">
            <article
              v-for="competency in qualitativeCompetencies"
              :key="competency.ref"
            >
              <span class="proposal-action">참고</span>
              <div>
                <strong>{{ competency.title }}</strong>
                <p>{{ competency.scopeDefinition }}</p>
              </div>
            </article>
          </div>
        </section>

        <section v-if="job.proposal?.targetProject" class="proposal-path-preview">
          <header>
            <div>
              <p class="eyebrow">TARGET PROJECT</p>
              <h2>{{ job.proposal.targetProject.title }}</h2>
            </div>
          </header>
          <p>{{ job.proposal.targetProject.objective }}</p>
          <div class="requirement-columns">
            <article>
              <h3>필수 결과물</h3>
              <ul>
                <li
                  v-for="item in job.proposal.targetProject.deliverables"
                  :key="item"
                >
                  {{ item }}
                </li>
              </ul>
            </article>
            <article>
              <h3>완료 기준</h3>
              <ul>
                <li
                  v-for="item in job.proposal.targetProject.acceptanceCriteria"
                  :key="item"
                >
                  {{ item }}
                </li>
              </ul>
            </article>
          </div>
        </section>

        <section
          v-if="job.changeSetStatus === 'PROPOSED'"
          class="proposal-decision-bar"
        >
          <div>
            <Clock3 :size="20" />
            <span>
              <strong>아직 목표 로드맵에는 포함되지 않았습니다</strong>
              <small v-if="required.length">
                추가하면 기존 지도는 유지되고 새 초안이 준비됩니다.
              </small>
              <small v-else>
                필수 조건이 구조화되지 않아 안전하게 지도에 반영할 수 없습니다. 공고 원문을 보완해 다시 분석해 주세요.
              </small>
            </span>
          </div>
          <button
            class="press-button press-button--ghost"
            type="button"
            :disabled="actionLoading"
            @click="reject"
          >
            <X :size="17" /> 반영하지 않기
          </button>
          <button
            class="press-button press-button--primary"
            type="button"
            :disabled="
              actionLoading ||
              !required.length
            "
            :title="
              !required.length
                ? '필수 조건이 없는 분석은 목표로 추가할 수 없습니다.'
                : undefined
            "
            @click="approve"
          >
            <Check :size="18" />
            {{ isClosedPosting ? '재오픈 대비 목표로 추가' : '목표 공고에 추가' }}
          </button>
        </section>
        <section
          v-else-if="job.changeSetStatus === 'APPROVED'"
          class="analysis-resolution analysis-resolution--applied"
        >
          <Check :size="18" /> 이 공고가 목표 목록에 추가되었습니다.
          <RouterLink
            class="text-action"
            :to="{ name: 'map', query: { posting: posting.id, preview: 'draft' } }"
          >
            지도에서 보기 <ArrowRight :size="14" />
          </RouterLink>
        </section>
        <section v-else class="analysis-resolution">
          이 분석의 지도 변경안은 반영하지 않았습니다.
        </section>
        </template>
      </template>

      <details class="posting-source-details">
        <summary>공고 원문 확인</summary>
        <pre>{{ posting.rawText }}</pre>
      </details>
    </template>
    <section v-else-if="error" class="state-panel state-panel--error">
      <h2>공고를 열 수 없습니다</h2>
      <p>{{ error }}</p>
      <RouterLink class="press-button press-button--secondary" :to="{ name: 'postings' }">
        채용 공고 목록으로 돌아가기
      </RouterLink>
    </section>
  </main>
</template>
