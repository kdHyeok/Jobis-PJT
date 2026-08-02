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
import type { AnalysisJob, PostingDetail, ProposedNode } from "@/types";

const route = useRoute();
const router = useRouter();
const posting = ref<PostingDetail | null>(null);
const job = ref<AnalysisJob | null>(null);
const loading = ref(true);
const actionLoading = ref(false);
const error = ref("");
const selectedAnswer = ref("");
const visibleQuestionId = ref<string | null>(null);
let pollTimer: number | null = null;

const postingId = computed(() => String(route.params.postingId));
const nodeByRef = computed(
  () =>
    new Map(
      (job.value?.proposal?.nodes ?? []).map((node) => [node.ref, node] as const),
    ),
);
const required = computed(() =>
  (job.value?.proposal?.requirements ?? []).filter(
    (requirement) => requirement.kind === "REQUIRED",
  ),
);
const preferred = computed(() =>
  (job.value?.proposal?.requirements ?? []).filter(
    (requirement) => requirement.kind === "PREFERRED",
  ),
);
const reused = computed(() =>
  (job.value?.proposal?.nodes ?? []).filter((node) => node.action === "REUSE"),
);
const created = computed(() =>
  (job.value?.proposal?.nodes ?? []).filter((node) => node.action === "CREATE"),
);

function verdictLabel(value?: string) {
  if (value === "APPLY_NOW") return "지금 지원";
  if (value === "STRENGTHEN_THEN_APPLY") return "보강 후 지원";
  if (value === "ALTERNATIVE_FIRST") return "대체 공고 우선";
  return "분석 결과";
}

function nodeTitle(ref: string) {
  return nodeByRef.value.get(ref)?.title ?? ref;
}

function nodeStatus(node: ProposedNode | undefined) {
  if (!node) return "확인 필요";
  return node.action === "REUSE" ? "현재 지도에서 재사용" : "새 경로로 제안";
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
    schedulePoll();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "공고를 불러오지 못했습니다.";
  } finally {
    loading.value = false;
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
    error.value = cause instanceof Error ? cause.message : "지도에 반영하지 못했습니다.";
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

      <section
        v-if="job && ['QUEUED', 'RUNNING'].includes(job.status)"
        class="analysis-progress-panel"
      >
        <AnalysisProgressWheel
          :status="job.status"
          :stage="job.stage"
          :stage-message="job.stageMessage"
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
        />
        <div class="analysis-question-panel__body">
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
            <p class="eyebrow">J.O.B.I.S EVALUATION</p>
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
              <h2>지도 변경 요약</h2>
            </header>
            <div>
              <span><strong>{{ reused.length }}</strong> 기존 역량 재사용</span>
              <span><strong>{{ created.length }}</strong> 새 노드 제안</span>
              <span><strong>{{ required.length }}</strong> 필수 조건</span>
              <span><strong>{{ preferred.length }}</strong> 우대 조건</span>
            </div>
          </article>
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
                :key="`${requirement.nodeRef}-required`"
                class="requirement-detail-row"
              >
                <span class="requirement-pill requirement-pill--required">필수</span>
                <div>
                  <strong>{{ nodeTitle(requirement.nodeRef) }}</strong>
                  <p>{{ requirement.sourceText }}</p>
                  <small>{{ nodeStatus(nodeByRef.get(requirement.nodeRef)) }}</small>
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
                :key="`${requirement.nodeRef}-preferred`"
                class="requirement-detail-row"
              >
                <span class="requirement-pill requirement-pill--preferred">우대</span>
                <div>
                  <strong>{{ nodeTitle(requirement.nodeRef) }}</strong>
                  <p>{{ requirement.sourceText }}</p>
                  <small>{{ nodeStatus(nodeByRef.get(requirement.nodeRef)) }}</small>
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
              <p class="eyebrow">GRAPH CHANGE</p>
              <h2>추가되거나 연결될 경로</h2>
            </div>
          </header>
          <div class="proposal-node-list">
            <article v-for="node in job.proposal?.nodes ?? []" :key="node.ref">
              <span :class="`proposal-action proposal-action--${node.action.toLowerCase()}`">
                {{ node.action === "REUSE" ? "재사용" : "새 경로" }}
              </span>
              <div>
                <strong>{{ node.title }}</strong>
                <p>{{ node.scopeDefinition }}</p>
                <small>{{ node.domain }} · {{ node.kind }} · Level {{ node.level }}</small>
              </div>
              <ArrowRight :size="17" />
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
              <strong>아직 커리어 지도에는 반영되지 않았습니다</strong>
              <small>내용을 검토한 뒤 직접 결정해 주세요.</small>
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
            :disabled="actionLoading"
            @click="approve"
          >
            <Check :size="18" /> 검토했고 지도에 반영
          </button>
        </section>
        <section
          v-else-if="job.changeSetStatus === 'APPROVED'"
          class="analysis-resolution analysis-resolution--applied"
        >
          <Check :size="18" /> 이 공고의 경로가 커리어 지도에 반영되었습니다.
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
