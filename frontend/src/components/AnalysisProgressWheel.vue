<script setup lang="ts">
import { computed } from "vue";

type AnalysisStage = {
  code: string;
  label: string;
  role: string;
  message: string;
  color: string;
};

const props = withDefaults(
  defineProps<{
    status: string;
    stage: string;
    stageMessage?: string | null;
    compact?: boolean;
  }>(),
  {
    stageMessage: null,
    compact: false,
  },
);

const stages: AnalysisStage[] = [
  {
    code: "QUEUED",
    label: "요청 접수",
    role: "접수 담당",
    message: "분석 순서를 확인하고 있어요.",
    color: "#ffb84d",
  },
  {
    code: "CONTEXT",
    label: "맥락 정리",
    role: "커리어 맥락 담당",
    message: "공고와 저장된 커리어 정보를 불러오고 있어요.",
    color: "#42c7b9",
  },
  {
    code: "AI_ANALYSIS",
    label: "공고 분석",
    role: "공고·경로 분석가",
    message: "필수·우대 조건과 커리어 경로를 분석하고 있어요.",
    color: "#4f8df7",
  },
  {
    code: "VALIDATING",
    label: "결과 검증",
    role: "계약 검증 담당",
    message: "지도 변경안의 누락과 연결 오류를 확인하고 있어요.",
    color: "#8b6cf6",
  },
  {
    code: "COMPLETED",
    label: "결과 조립",
    role: "결과 조립 담당",
    message: "지원 판단과 지도 변경안을 정리했어요.",
    color: "#ef6f9b",
  },
];

const currentIndex = computed(() => {
  if (props.status === "SUCCEEDED" || props.stage === "COMPLETED") {
    return stages.length - 1;
  }
  if (props.status === "WAITING_FOR_INPUT" || props.stage === "WAITING_FOR_INPUT") {
    return 2;
  }
  const found = stages.findIndex((item) => item.code === props.stage);
  return found >= 0 ? found : 0;
});

const currentStage = computed<AnalysisStage>(() => {
  if (props.status === "WAITING_FOR_INPUT") {
    return {
      ...stages[2],
      label: "기준 확인",
      role: "기준 확인 담당",
      message: "분석 기준을 정하기 위해 답변을 기다리고 있어요.",
      color: "#f29d38",
    };
  }
  return stages[currentIndex.value];
});

const progressLabel = computed(() => {
  if (props.status === "WAITING_FOR_INPUT") return "답변 대기";
  if (props.status === "SUCCEEDED") return "완료";
  return `${currentIndex.value + 1}/${stages.length}`;
});

function point(angle: number, radius: number) {
  const radians = (angle * Math.PI) / 180;
  return {
    x: 60 + radius * Math.cos(radians),
    y: 60 + radius * Math.sin(radians),
  };
}

function slicePath(index: number) {
  const size = 360 / stages.length;
  const gap = 2.2;
  const startAngle = -90 + index * size + gap;
  const endAngle = -90 + (index + 1) * size - gap;
  const start = point(startAngle, 49);
  const end = point(endAngle, 49);
  const largeArc = endAngle - startAngle > 180 ? 1 : 0;
  return [
    "M 60 60",
    `L ${start.x.toFixed(3)} ${start.y.toFixed(3)}`,
    `A 49 49 0 ${largeArc} 1 ${end.x.toFixed(3)} ${end.y.toFixed(3)}`,
    "Z",
  ].join(" ");
}

function sliceTransform(index: number) {
  if (index !== currentIndex.value || props.status === "SUCCEEDED") return undefined;
  const middle = -90 + (index + 0.5) * (360 / stages.length);
  const offset = point(middle, 3.5);
  return `translate(${(offset.x - 60).toFixed(2)} ${(offset.y - 60).toFixed(2)})`;
}

function sliceClass(index: number) {
  return {
    "analysis-wheel__slice--done":
      index < currentIndex.value || props.status === "SUCCEEDED",
    "analysis-wheel__slice--active":
      index === currentIndex.value && props.status !== "SUCCEEDED",
    "analysis-wheel__slice--waiting":
      index === currentIndex.value && props.status === "WAITING_FOR_INPUT",
    "analysis-wheel__slice--upcoming":
      index > currentIndex.value && props.status !== "SUCCEEDED",
  };
}
</script>

<template>
  <div class="analysis-wheel" :class="{ 'analysis-wheel--compact': compact }">
    <div class="analysis-wheel__graphic">
      <svg
        viewBox="0 0 120 120"
        role="img"
        :aria-label="`공고 분석 ${currentStage.label} 단계`"
      >
        <path
          v-for="(item, index) in stages"
          :key="item.code"
          class="analysis-wheel__slice"
          :class="sliceClass(index)"
          :d="slicePath(index)"
          :fill="
            index === currentIndex && status === 'WAITING_FOR_INPUT'
              ? currentStage.color
              : item.color
          "
          :transform="sliceTransform(index)"
        >
          <title>{{ index + 1 }}단계 {{ item.label }}</title>
        </path>
        <circle class="analysis-wheel__hub" cx="60" cy="60" r="23" />
      </svg>
      <div class="analysis-wheel__center">
        <small>{{ status === "WAITING_FOR_INPUT" ? "PAUSE" : "STEP" }}</small>
        <strong>{{ progressLabel }}</strong>
      </div>
    </div>

    <div class="analysis-wheel__copy">
      <p class="eyebrow">{{ currentStage.label }}</p>
      <h2>{{ currentStage.role }}</h2>
      <p>{{ stageMessage || currentStage.message }}</p>

      <ol v-if="!compact" class="analysis-wheel__legend">
        <li
          v-for="(item, index) in stages"
          :key="item.code"
          :class="{
            done: index < currentIndex || status === 'SUCCEEDED',
            active: index === currentIndex && status !== 'SUCCEEDED',
          }"
        >
          <i :style="{ backgroundColor: item.color }" />
          <span>{{ item.label }}</span>
          <b v-if="index < currentIndex || status === 'SUCCEEDED'">✓</b>
        </li>
      </ol>
    </div>
  </div>
</template>
