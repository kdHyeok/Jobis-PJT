<script setup lang="ts">
import {
  Check,
  ClipboardCheck,
  FileSearch,
  Layers3,
  PackageCheck,
  ShieldCheck,
  Sparkles,
  type LucideIcon,
} from "@lucide/vue";
import { computed, onBeforeUnmount, ref, watch } from "vue";

import type {
  AnalysisProgressEvent,
  AnalysisStageDefinition,
  AnalysisStageUpdate,
} from "@/types";

type AnalysisStage = AnalysisStageDefinition & {
  code: string;
  icon: LucideIcon;
};

const props = withDefaults(
  defineProps<{
    status: string;
    stage: string;
    stageMessage?: string | null;
    queuePosition?: number | null;
    events?: AnalysisProgressEvent[];
    compact?: boolean;
  }>(),
  {
    stageMessage: null,
    queuePosition: null,
    events: () => [],
    compact: false,
  },
);

const fallbackStages: AnalysisStage[] = [
  {
    id: "CONTEXT_ASSEMBLY",
    code: "CONTEXT_ASSEMBLY",
    label: "분석 자료 준비",
    role: "공고와 커리어 자료를 준비하고 있어요",
    message: "공고와 커리어 근거를 분석 입력으로 조립하고 있어요.",
    color: "#1cb0f6",
    icon: ClipboardCheck,
  },
  {
    id: "CLARIFICATION",
    code: "CLARIFICATION",
    label: "분석 기준 확인",
    role: "정확한 분석에 필요한 조건을 확인하고 있어요",
    message: "결과를 바꿀 모호한 조건이 있는지 확인하고 있어요.",
    color: "#ff9600",
    icon: Layers3,
  },
  {
    id: "POSTING_ANALYSIS",
    code: "POSTING_ANALYSIS",
    label: "지원 준비도 분석",
    role: "공고 조건과 현재 경험을 비교하고 있어요",
    message: "필수·우대 조건과 현재 근거를 구조화하고 있어요.",
    color: "#ce82ff",
    icon: FileSearch,
  },
  {
    id: "CONTRACT_VALIDATION",
    code: "CONTRACT_VALIDATION",
    label: "분석 결과 확인",
    role: "빠진 조건이나 잘못된 연결이 없는지 확인하고 있어요",
    message: "스키마와 참조 무결성을 코드로 검증하고 있어요.",
    color: "#2b70c9",
    icon: ShieldCheck,
  },
  {
    id: "RESULT_ASSEMBLY",
    code: "RESULT_ASSEMBLY",
    label: "로드맵 반영안 준비",
    role: "지원 판단과 새 로드맵 초안을 정리하고 있어요",
    message: "지원 판단과 로드맵 변경안을 정리하고 있어요.",
    color: "#58cc02",
    icon: PackageCheck,
  },
];

const pipelineStageGroups: Array<AnalysisStage & { members: string[] }> = [
  {
    id: "POSTING_INTERPRETATION",
    code: "POSTING_INTERPRETATION",
    label: "공고 해석",
    role: "공고 해석 에이전트",
    message: "회사와 모집 직무, 담당 업무를 원문 근거로 확인하고 있어요.",
    color: "#1cb0f6",
    icon: ClipboardCheck,
    members: [
      "SOURCE_FETCH",
      "SOURCE_EXTRACT",
      "AWAITING_SOURCE_VERIFICATION",
      "POSITION_DISCOVERY",
      "POSTING_DETAIL",
      "POSTING_STRUCTURE",
    ],
  },
  {
    id: "ANALYSIS_CRITERIA",
    code: "ANALYSIS_CRITERIA",
    label: "분석 기준 확인",
    role: "조건 확인 에이전트",
    message: "분석할 직무와 경력 기준을 확인하고 있어요.",
    color: "#ff9600",
    icon: Layers3,
    members: [
      "AWAITING_POSITION_SELECTION",
      "AWAITING_EXPERIENCE_TRACK_SELECTION",
      "AWAITING_POSTING_CONFIRMATION",
    ],
  },
  {
    id: "PROJECT_DESIGN",
    code: "PROJECT_DESIGN",
    label: "맞춤 프로젝트 설계",
    role: "프로젝트 설계 에이전트",
    message: "실제 업무를 증명할 회사 맞춤 프로젝트와 수행 과제를 설계하고 있어요.",
    color: "#ce82ff",
    icon: FileSearch,
    members: ["PROJECT_PLANNING"],
  },
  {
    id: "CAPABILITY_PATH",
    code: "CAPABILITY_PATH",
    label: "역량 경로 구성",
    role: "역량 경로 에이전트",
    message: "프로젝트에 필요한 원자 역량과 선수 학습 관계를 연결하고 있어요.",
    color: "#2b70c9",
    icon: ShieldCheck,
    members: [
      "CAPABILITY_NORMALIZATION",
      "CAPABILITY_GRAPH_LOOKUP",
      "PROFILE_ASSEMBLY",
      "FIT_ANALYSIS",
      "AWAITING_USER_EVIDENCE",
    ],
  },
  {
    id: "CAREER_ROADMAP",
    code: "CAREER_ROADMAP",
    label: "커리어 그래프 조립",
    role: "로드맵 에이전트",
    message: "프로젝트, 경력 조건과 지원 기회를 하나의 커리어 그래프로 정리하고 있어요.",
    color: "#58cc02",
    icon: PackageCheck,
    members: ["ROADMAP_PROPOSAL", "CONTRACT_VALIDATION", "RESULT_ASSEMBLY"],
  },
];

function displayStageId(stage: string) {
  return pipelineStageGroups.find((group) => group.members.includes(stage))?.id ?? stage;
}

const stageIcons: LucideIcon[] = [
  ClipboardCheck,
  Layers3,
  FileSearch,
  ShieldCheck,
  PackageCheck,
  Sparkles,
];

const v3Events = computed(() =>
  props.events
    .filter((event) => event.type === "PROGRESS" && event.progress)
    .sort((left, right) => left.sequence - right.sequence),
);

const maximumSequence = computed(() =>
  Math.max(0, ...props.events.map((event) => event.sequence ?? 0)),
);
const revealedSequence = ref(0);
let revealTimer: number | null = null;

function continueReveal() {
  if (revealTimer !== null || revealedSequence.value >= maximumSequence.value) return;
  revealTimer = window.setTimeout(() => {
    revealTimer = null;
    const next = props.events
      .map((event) => event.sequence)
      .filter((sequence) => sequence > revealedSequence.value)
      .sort((left, right) => left - right)[0];
    if (next !== undefined) revealedSequence.value = next;
    continueReveal();
  }, 420);
}

watch(
  () => props.events.map((event) => event.sequence).join(","),
  () => {
    if (!props.events.length) return;
    if (revealedSequence.value === 0) {
      revealedSequence.value = Math.min(...props.events.map((event) => event.sequence));
    }
    continueReveal();
  },
  { immediate: true },
);

onBeforeUnmount(() => {
  if (revealTimer !== null) window.clearTimeout(revealTimer);
});

const stages = computed<AnalysisStage[]>(() => {
  if (v3Events.value.length) {
    // 세부 이벤트가 한 건 도착했다고 5단계 계획이 1단계로 줄어들지 않도록
    // 사용자에게 의미 있는 역할 단위로 고정한다. 세부 stage는 아래 update에서
    // 해당 역할에 합쳐지고, 원문 계약에는 그대로 보존된다.
    return pipelineStageGroups;
  }
  const plan = [...props.events]
    .reverse()
    .find((event) => event.type === "RUN_STARTED" && (event.stages?.length ?? 0) > 0);
  if (!plan) return fallbackStages;
  return plan.stages!.map((item, index) => ({
    ...item,
    code: item.id,
    icon: stageIcons[index % stageIcons.length],
  }));
});

const stageUpdates = computed<Map<string, AnalysisStageUpdate>>(() => {
  const updates = new Map<string, AnalysisStageUpdate>();
  v3Events.value
    .filter((event) => event.sequence <= revealedSequence.value)
    .forEach((event) => {
      const progress = event.progress!;
      const status = progress.status === "SKIPPED"
        ? "COMPLETED"
        : progress.status === "CANCELLED"
          ? "FAILED"
          : progress.status;
      const stageId = displayStageId(progress.stage);
      updates.set(stageId, {
        id: stageId,
        status: status as AnalysisStageUpdate["status"],
        message: progress.detail || progress.label,
      });
    });
  props.events
    .filter((event) => event.sequence <= revealedSequence.value)
    .filter((event) => event.type === "STAGE_UPDATED" && event.stage)
    .sort((left, right) => left.sequence - right.sequence)
    .forEach((event) => updates.set(event.stage!.id, event.stage!));
  return updates;
});

const currentIndex = computed(() => {
  const items = stages.value;
  if (visualComplete.value) return items.length - 1;

  for (let index = items.length - 1; index >= 0; index -= 1) {
    const update = stageUpdates.value.get(items[index].id);
    if (
      update &&
      ["RUNNING", "WAITING", "FAILED"].includes(update.status)
    ) {
      return index;
    }
  }

  const displayStage = displayStageId(props.stage);
  const found = items.findIndex((item) => item.code === displayStage);
  if (found >= 0) return found;
  if (props.status === "WAITING_FOR_INPUT") {
    return Math.min(2, items.length - 1);
  }
  return 0;
});

const visualComplete = computed(() =>
  props.status === "SUCCEEDED" && revealedSequence.value >= maximumSequence.value,
);

const currentStage = computed<AnalysisStage>(() => {
  const base = stages.value[currentIndex.value] ?? fallbackStages[0];
  if (props.status === "WAITING_FOR_INPUT") {
    if (props.stage === "AWAITING_POSTING_CONFIRMATION") {
      return {
        ...base,
        label: "공고 범위 확인",
        role: "프로젝트를 만들기 전 마지막 확인",
        message: "선택한 직무와 경력 기준에 맞는 업무·필수·우대 조건을 확인해 주세요.",
        color: "#1cb0f6",
      };
    }
    return {
      ...base,
      label: "기준 확인",
      role: "사용자 답변 대기",
      message: "더 정확한 경로를 만들기 위해 답변을 기다리고 있어요.",
      color: "#ffc800",
    };
  }
  if (props.status === "FAILED") {
    return {
      ...base,
      label: "분석 중단",
      role: "다시 확인이 필요해요",
      message: "오류를 확인한 뒤 같은 분석을 다시 시작할 수 있어요.",
      color: "#ff4b4b",
    };
  }
  return base;
});

const progressLabel = computed(() => {
  if (props.status === "WAITING_FOR_INPUT") return "대기";
  if (visualComplete.value) return "완료";
  if (props.status === "FAILED") return "중단";
  return `${currentIndex.value + 1}/${stages.value.length}`;
});

const completedStageCount = computed(
  () => stages.value.filter((_, index) => isDone(index)).length,
);

const displayMessage = computed(() => {
  if (props.status === "QUEUED") {
    if ((props.queuePosition ?? 0) > 0) {
      return `앞에 분석 작업이 ${props.queuePosition}개 있어요. 다른 화면을 이용해도 차례가 되면 자동으로 시작됩니다.`;
    }
    return "분석을 시작할 준비를 하고 있어요. 다른 화면을 이용해도 자동으로 진행됩니다.";
  }
  const update = stageUpdates.value.get(
    stages.value[currentIndex.value]?.id ?? "",
  );
  return (
    update?.message ||
    props.stageMessage ||
    currentStage.value.message
  );
});

const latestPartial = computed(() => {
  const event = [...v3Events.value]
    .filter((item) => item.sequence <= revealedSequence.value)
    .reverse()
    .find((item) => item.progress?.partialResult);
  return event?.progress?.partialResult ?? null;
});

const partialLines = computed(() => {
  const partial = latestPartial.value;
  if (!partial) return [];
  if (partial.positions?.length) {
    return partial.positions.slice(0, 4).map((position) => {
      const months = position.experiencedMinMonths ?? position.minMonths;
      const experience = months
        ? ` · 경력 ${Math.floor(months / 12)}년${months % 12 ? ` ${months % 12}개월` : ""}`
        : "";
      return `${position.title}${experience}`;
    });
  }
  return [
    ...(partial.requiredPreview ?? []),
    ...(partial.preferredPreview ?? []),
    ...(partial.taskPreview ?? []),
  ].slice(0, 4);
});

function stageState(index: number) {
  return stageUpdates.value.get(stages.value[index]?.id ?? "")?.status;
}

function isDone(index: number) {
  return visualComplete.value || stageState(index) === "COMPLETED";
}

function agentClass(index: number) {
  const state = stageState(index);
  return {
    done: isDone(index),
    active:
      index === currentIndex.value &&
      !visualComplete.value &&
      props.status !== "FAILED",
    waiting:
      index === currentIndex.value &&
      (props.status === "WAITING_FOR_INPUT" || state === "WAITING"),
    error:
      index === currentIndex.value &&
      (props.status === "FAILED" || state === "FAILED"),
    upcoming:
      !isDone(index) &&
      index !== currentIndex.value &&
      state !== "FAILED",
  };
}

function agentStyle(index: number) {
  const count = Math.max(stages.value.length, 1);
  const angle = ((-90 + index * (360 / count)) * Math.PI) / 180;
  return {
    "--agent-color": stages.value[index].color,
    left: `${50 + Math.cos(angle) * 41}%`,
    top: `${50 + Math.sin(angle) * 41}%`,
  };
}
</script>

<template>
  <div
    class="analysis-wheel"
    :class="{
      'analysis-wheel--compact': compact,
      'analysis-wheel--waiting': status === 'WAITING_FOR_INPUT',
      'analysis-wheel--error': status === 'FAILED',
      'analysis-wheel--complete': status === 'SUCCEEDED',
    }"
  >
    <template v-if="compact">
      <div class="analysis-wheel__compact-status" aria-live="polite">
        <span
          class="analysis-wheel__compact-icon"
          :class="{
            'is-complete': status === 'SUCCEEDED',
            'is-waiting': status === 'WAITING_FOR_INPUT',
            'is-error': status === 'FAILED',
          }"
          :style="{ '--agent-color': currentStage.color }"
        >
          <Check v-if="status === 'SUCCEEDED'" :size="18" :stroke-width="3.5" />
          <component v-else :is="currentStage.icon" :size="18" />
        </span>
        <div>
          <small>{{ currentStage.label }}</small>
          <strong>{{ currentStage.role }}</strong>
        </div>
        <b>{{ progressLabel }}</b>
      </div>
      <div
        class="analysis-wheel__compact-trail"
        role="progressbar"
        :aria-valuenow="completedStageCount"
        :aria-valuemax="stages.length"
        aria-label="지원 준비도와 커리어 지도 분석 진행률"
      >
        <span
          v-for="(item, index) in stages"
          :key="item.code"
          :class="agentClass(index)"
          :style="{ '--agent-color': item.color }"
          :title="`${item.label}: ${stageState(index) ?? 'PENDING'}`"
        />
      </div>
      <p class="analysis-wheel__compact-message">{{ displayMessage }}</p>
      <section v-if="latestPartial" class="analysis-wheel__partial" aria-live="polite">
        <small>현재까지 확인한 내용</small>
        <strong>{{ latestPartial.title }}</strong>
        <p v-if="latestPartial.company">{{ latestPartial.company }}</p>
        <p v-if="latestPartial.summary">{{ latestPartial.summary }}</p>
        <ul v-if="partialLines.length">
          <li v-for="line in partialLines" :key="line">{{ line }}</li>
        </ul>
      </section>
      <details class="analysis-wheel__compact-details">
        <summary>작업 단계 보기</summary>
        <ol>
          <li
            v-for="(item, index) in stages"
            :key="item.code"
            :class="agentClass(index)"
            :style="{ '--agent-color': item.color }"
          >
            <i />
            <span>{{ item.label }}</span>
            <small>{{ isDone(index) ? "완료" : index === currentIndex ? "진행 중" : "대기" }}</small>
          </li>
        </ol>
      </details>
    </template>

    <template v-else>
    <div
      class="analysis-wheel__graphic"
      role="img"
      :aria-label="`공고 분석 ${currentStage.label} 단계, ${currentStage.role}`"
    >
      <div class="analysis-wheel__orbit" aria-hidden="true">
        <span
          v-for="(item, index) in stages"
          :key="item.code"
          class="analysis-wheel__agent"
          :class="agentClass(index)"
          :style="agentStyle(index)"
        >
          <component :is="item.icon" :size="20" stroke-width="2.8" />
          <span v-if="isDone(index)" class="analysis-wheel__agent-check">
            <Check :size="11" stroke-width="4" />
          </span>
        </span>

        <div class="analysis-wheel__center">
          <div class="analysis-guide-character">
            <span class="analysis-guide-character__antenna" />
            <span
              class="analysis-guide-character__eye analysis-guide-character__eye--left"
            />
            <span
              class="analysis-guide-character__eye analysis-guide-character__eye--right"
            />
            <span class="analysis-guide-character__smile" />
          </div>
          <strong>{{ progressLabel }}</strong>
        </div>
      </div>
    </div>

    <div class="analysis-wheel__copy" aria-live="polite">
      <p class="eyebrow">{{ currentStage.label }}</p>
      <h2>{{ currentStage.role }}</h2>
      <p>{{ displayMessage }}</p>
      <section v-if="latestPartial" class="analysis-wheel__partial" aria-live="polite">
        <small>현재까지 확인한 내용</small>
        <strong>{{ latestPartial.title }}</strong>
        <p v-if="latestPartial.company">{{ latestPartial.company }}</p>
        <p v-if="latestPartial.summary">{{ latestPartial.summary }}</p>
        <ul v-if="partialLines.length">
          <li v-for="line in partialLines" :key="line">{{ line }}</li>
        </ul>
      </section>

      <ol class="analysis-wheel__legend">
        <li
          v-for="(item, index) in stages"
          :key="item.code"
          :class="agentClass(index)"
          :style="{ '--agent-color': item.color }"
        >
          <span class="analysis-wheel__legend-icon">
            <component :is="item.icon" :size="16" />
          </span>
          <span>
            <small>{{ index + 1 }}단계</small>
            <strong>{{ item.label }}</strong>
          </span>
          <Check v-if="isDone(index)" :size="15" stroke-width="3.5" />
        </li>
      </ol>
    </div>
    </template>
  </div>
</template>

<style scoped>
.analysis-wheel__partial {
  margin-top: 12px;
  padding: 14px 16px;
  border: 2px solid #dbeafe;
  border-radius: 16px;
  background: #f7fbff;
  box-shadow: 0 3px 0 #dbeafe;
}

.analysis-wheel__partial small,
.analysis-wheel__partial strong {
  display: block;
}

.analysis-wheel__partial small {
  margin-bottom: 4px;
  color: #2b70c9;
  font-weight: 800;
}

.analysis-wheel__partial strong {
  color: #17365f;
  font-size: 0.98rem;
}

.analysis-wheel__partial p {
  margin: 5px 0 0;
  color: #4b6280;
}

.analysis-wheel__partial ul {
  display: grid;
  gap: 4px;
  margin: 8px 0 0;
  padding-left: 18px;
  color: #334d6e;
  font-size: 0.88rem;
}
</style>
