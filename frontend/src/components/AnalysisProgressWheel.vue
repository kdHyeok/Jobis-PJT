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
import { computed } from "vue";

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
    label: "맥락 조립",
    role: "대화 오케스트레이터",
    message: "공고와 커리어 근거를 분석 입력으로 조립하고 있어요.",
    color: "#1cb0f6",
    icon: ClipboardCheck,
  },
  {
    id: "CLARIFICATION",
    code: "CLARIFICATION",
    label: "기준 확인",
    role: "사전 확인 에이전트",
    message: "결과를 바꿀 모호한 조건이 있는지 확인하고 있어요.",
    color: "#ff9600",
    icon: Layers3,
  },
  {
    id: "POSTING_ANALYSIS",
    code: "POSTING_ANALYSIS",
    label: "공고 분석",
    role: "공고·적합도 분석 에이전트",
    message: "필수·우대 조건과 현재 근거를 구조화하고 있어요.",
    color: "#ce82ff",
    icon: FileSearch,
  },
  {
    id: "CONTRACT_VALIDATION",
    code: "CONTRACT_VALIDATION",
    label: "결과 검증",
    role: "결정론 검증기",
    message: "스키마와 참조 무결성을 코드로 검증하고 있어요.",
    color: "#2b70c9",
    icon: ShieldCheck,
  },
  {
    id: "RESULT_ASSEMBLY",
    code: "RESULT_ASSEMBLY",
    label: "결과 조립",
    role: "경로 조립",
    message: "지원 판단과 로드맵 변경안을 정리하고 있어요.",
    color: "#58cc02",
    icon: PackageCheck,
  },
];

const stageIcons: LucideIcon[] = [
  ClipboardCheck,
  Layers3,
  FileSearch,
  ShieldCheck,
  PackageCheck,
  Sparkles,
];

const stages = computed<AnalysisStage[]>(() => {
  const plan = [...props.events]
    .reverse()
    .find((event) => event.type === "RUN_STARTED" && event.stages.length > 0);
  if (!plan) return fallbackStages;
  return plan.stages.map((item, index) => ({
    ...item,
    code: item.id,
    icon: stageIcons[index % stageIcons.length],
  }));
});

const stageUpdates = computed<Map<string, AnalysisStageUpdate>>(() => {
  const updates = new Map<string, AnalysisStageUpdate>();
  props.events
    .filter((event) => event.type === "STAGE_UPDATED" && event.stage)
    .sort((left, right) => left.sequence - right.sequence)
    .forEach((event) => updates.set(event.stage!.id, event.stage!));
  return updates;
});

const currentIndex = computed(() => {
  const items = stages.value;
  if (props.status === "SUCCEEDED") return items.length - 1;

  for (let index = items.length - 1; index >= 0; index -= 1) {
    const update = stageUpdates.value.get(items[index].id);
    if (
      update &&
      ["RUNNING", "WAITING", "FAILED"].includes(update.status)
    ) {
      return index;
    }
  }

  const found = items.findIndex((item) => item.code === props.stage);
  if (found >= 0) return found;
  if (props.status === "WAITING_FOR_INPUT") {
    return Math.min(2, items.length - 1);
  }
  return 0;
});

const visualComplete = computed(() => props.status === "SUCCEEDED");

const currentStage = computed<AnalysisStage>(() => {
  const base = stages.value[currentIndex.value] ?? fallbackStages[0];
  if (props.status === "WAITING_FOR_INPUT") {
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

const displayMessage = computed(() => {
  if (props.status === "QUEUED" && props.queuePosition) {
    return `현재 대기 순서 ${props.queuePosition}번째예요. 다른 화면을 이용해도 분석은 자동으로 시작됩니다.`;
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

      <div v-if="compact" class="analysis-wheel__compact-trail" aria-label="완료한 분석 단계">
        <span
          v-for="(item, index) in stages"
          :key="item.code"
          :class="agentClass(index)"
          :style="{ '--agent-color': item.color }"
          :title="`${item.label}: ${stageState(index) ?? 'PENDING'}`"
        />
      </div>

      <ol v-if="!compact" class="analysis-wheel__legend">
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
  </div>
</template>
