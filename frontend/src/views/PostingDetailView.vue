<script setup lang="ts">
import {
  ArrowLeft,
  ArrowRight,
  Check,
  ChevronRight,
  CircleAlert,
  Clock3,
  ExternalLink,
  LoaderCircle,
  RefreshCw,
  Sparkles,
  X,
} from "@lucide/vue";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api } from "@/api";
import AnalysisProgressWheel from "@/components/AnalysisProgressWheel.vue";
import type {
  AlternativePosting,
  AnalysisJob,
  AnalyzedCompetency,
  PostingDetail,
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
let pollTimer: number | null = null;

const postingId = computed(() => String(route.params.postingId));
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
const qualitativeCompetencies = computed(() =>
  (job.value?.proposal?.competencies ?? []).filter(
    (competency) => competency.roadmapEligible === false,
  ),
);
const required = computed(() =>
  (job.value?.proposal?.requirements ?? []).filter(
    (requirement) =>
      requirement.relation === "REQUIRED" &&
      competencyByRef.value.get(requirement.competencyRef)?.roadmapEligible !== false,
  ),
);
const preferred = computed(() =>
  (job.value?.proposal?.requirements ?? []).filter(
    (requirement) =>
      requirement.relation === "PREFERRED" &&
      competencyByRef.value.get(requirement.competencyRef)?.roadmapEligible !== false,
  ),
);
const responsibilities = computed(() =>
  (job.value?.proposal?.requirements ?? []).filter(
    (requirement) => requirement.relation === "RESPONSIBILITY",
  ),
);

function verdictLabel(value?: string) {
  if (value === "APPLY_NOW") return "지금 지원";
  if (value === "STRENGTHEN_THEN_APPLY") return "보강 후 지원";
  if (value === "ALTERNATIVE_FIRST") return "대체 공고 우선";
  return "분석 결과";
}

function competencyTitle(ref: string) {
  return competencyByRef.value.get(ref)?.title ?? ref;
}

function competencyStatus(competency: AnalyzedCompetency | undefined) {
  if (!competency) return "확인 필요";
  return `${competency.stage} 단계 · 요구 수준 ${competency.requiredLevel}`;
}

async function load() {
  error.value = "";
  try {
    posting.value = await api.posting(postingId.value);
    job.value = posting.value.analysisJobId
      ? await api.analysisJob(posting.value.analysisJobId)
      : null;
    if (job.value?.pendingQuestion?.id !== visibleQuestionId.value) {
      visibleQuestionId.value = job.value?.pendingQuestion?.id ?? null;
      selectedAnswer.value = "";
    }
    if (job.value?.status === "SUCCEEDED" && !alternativesLoaded.value) {
      void loadAlternatives();
    }
    schedulePoll();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "공고를 불러오지 못했습니다.";
  } finally {
    loading.value = false;
  }
}

async function loadAlternatives() {
  alternativesLoading.value = true;
  try {
    alternatives.value = await api.alternativePostings(postingId.value);
    alternativesLoaded.value = true;
  } catch {
    alternatives.value = [];
  } finally {
    alternativesLoading.value = false;
  }
}

function schedulePoll() {
  if (pollTimer) window.clearTimeout(pollTimer);
  if (!job.value || !["QUEUED", "RUNNING"].includes(job.value.status)) return;
  pollTimer = window.setTimeout(() => void load(), 2500);
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

async function answerQuestion() {
  const currentJob = job.value;
  const question = currentJob?.pendingQuestion;
  if (!currentJob || !question || !selectedAnswer.value) return;
  actionLoading.value = true;
  error.value = "";
  try {
    await api.answerAnalysisQuestion(
      currentJob.id,
      question.id,
      selectedAnswer.value,
    );
    await load();
  } catch (cause) {
    error.value =
      cause instanceof Error ? cause.message : "답변을 반영하지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

async function approve() {
  if (!job.value) return;
  actionLoading.value = true;
  try {
    await api.approveAnalysis(job.value.id);
    await router.push({ name: "map", query: { posting: postingId.value } });
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "목표 공고에 추가하지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

async function reject() {
  if (!job.value || !window.confirm("이 지도 변경안을 반영하지 않을까요?")) return;
  actionLoading.value = true;
  try {
    await api.rejectAnalysis(job.value.id);
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "변경안을 거절하지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

onMounted(load);
onBeforeUnmount(() => {
  if (pollTimer) window.clearTimeout(pollTimer);
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
            모집 마감 · 학습 참고용
          </span>
        </div>
        <a
          v-if="posting.sourceUrl"
          class="press-button press-button--ghost"
          :href="posting.sourceUrl"
          target="_blank"
          rel="noopener noreferrer"
        >
          원본 공고 <ExternalLink :size="16" />
        </a>
      </section>

      <p v-if="error" class="form-error">{{ error }}</p>
      <p
        v-if="['EXPIRED', 'CLOSED'].includes(posting.lifecycleStatus ?? '')"
        class="posting-closed-notice"
      >
        마감된 공고입니다. 분석 결과는 보관되지만 현재 지원 목표로 추가할 수
        없으며, 아래 대체 공고를 함께 확인할 수 있습니다.
      </p>

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
        <div class="analysis-question-panel__body">
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
            QUICK CHECK · {{ job.pendingQuestion.ordinal }}/3
          </p>
          <h2>{{ job.pendingQuestion.text }}</h2>
          <p>{{ job.pendingQuestion.reason }}</p>
          <div class="analysis-question-options">
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
            @click="answerQuestion"
          >
            <LoaderCircle v-if="actionLoading" class="spin" :size="18" />
            <Check v-else :size="18" />
            이 답변으로 분석 계속하기
          </button>
          <small class="analysis-question-note">
            답변을 반영한 뒤 같은 분석 작업을 백그라운드에서 이어갑니다.
          </small>
        </div>
      </section>

      <section v-else-if="job?.status === 'FAILED'" class="analysis-progress-panel analysis-progress-panel--error">
        <span><CircleAlert :size="24" /></span>
        <div>
          <p class="eyebrow">ANALYSIS FAILED</p>
          <h2>공고 분석을 완료하지 못했습니다</h2>
          <p>{{ job.errorMessage }}</p>
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
        <section class="evaluation-banner">
          <div>
            <p class="eyebrow">JOBISS EVALUATION</p>
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
                aria-label="원본 공고 열기"
              >
                <ExternalLink :size="18" />
              </a>
            </article>
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
              <small>추가하면 기존 지도는 유지되고 새 초안이 준비됩니다.</small>
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
              ['EXPIRED', 'CLOSED'].includes(posting.lifecycleStatus ?? '')
            "
            :title="
              ['EXPIRED', 'CLOSED'].includes(posting.lifecycleStatus ?? '')
                ? '마감된 공고는 목표로 추가할 수 없습니다.'
                : undefined
            "
            @click="approve"
          >
            <Check :size="18" /> 목표 공고에 추가
          </button>
        </section>
        <section
          v-else-if="job.changeSetStatus === 'APPROVED'"
          class="analysis-resolution analysis-resolution--applied"
        >
          <Check :size="18" /> 이 공고가 목표 목록에 추가되었습니다.
          <RouterLink class="text-action" :to="{ name: 'map', query: { posting: posting.id } }">
            지도에서 보기 <ArrowRight :size="14" />
          </RouterLink>
        </section>
        <section v-else class="analysis-resolution">
          이 분석의 지도 변경안은 반영하지 않았습니다.
        </section>
      </template>

      <details class="posting-source-details">
        <summary>공고 원문 확인</summary>
        <pre>{{ posting.rawText }}</pre>
      </details>
    </template>
  </main>
</template>
