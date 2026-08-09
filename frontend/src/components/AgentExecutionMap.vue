<script setup lang="ts">
import { ChevronDown, CircleAlert, LoaderCircle, Sparkles } from "@lucide/vue";
import { computed } from "vue";

import type {
  AgentExecutionPlan,
  AgentProgressEvent,
  PlannedAgent,
} from "@/types";

const props = withDefaults(
  defineProps<{
    plan?: AgentExecutionPlan | null;
    events?: AgentProgressEvent[];
    status?: string | null;
    compact?: boolean;
  }>(),
  { plan: null, events: () => [], status: null, compact: false },
);

const latestEvents = computed(() => {
  const values = new Map<string, AgentProgressEvent>();
  for (const event of props.events) values.set(event.agentId, event);
  return values;
});

const agents = computed<PlannedAgent[]>(() => {
  const source = props.plan?.agents?.length
    ? props.plan.agents
    : [...latestEvents.value.values()].map((event, index) => ({
        runId: `progress-${event.agentId}-${index}`,
        agentId: event.agentId,
        label: event.label,
        groupIndex: index,
        orderIndex: index,
        reason: event.message,
        status: event.status,
      }));
  return [...source]
    .sort((left, right) =>
      left.groupIndex === right.groupIndex
        ? left.orderIndex - right.orderIndex
        : left.groupIndex - right.groupIndex,
    )
    .map((agent) => {
      const event = latestEvents.value.get(agent.agentId);
      return {
        ...agent,
        label: userLabel(agent.agentId, event?.label ?? agent.label),
        reason: event?.message ?? agent.reason,
        status: event?.status ?? agent.status,
      };
    });
});

const completedCount = computed(
  () => agents.value.filter((agent) => agent.status === "COMPLETED").length,
);
const failed = computed(
  () => props.status === "FAILED" || agents.value.some((agent) => agent.status === "FAILED"),
);
const allAgentsComplete = computed(
  () => agents.value.length > 0 && completedCount.value === agents.value.length,
);
const allComplete = computed(
  () => allAgentsComplete.value && (!props.status || props.status === "SUCCEEDED"),
);
const wrappingUp = computed(
  () => props.status === "RUNNING" && allAgentsComplete.value,
);
const activeAgent = computed(
  () =>
    agents.value.find((agent) => agent.status === "RUNNING") ??
    agents.value.find((agent) => agent.status === "NEEDS_CONFIRMATION") ??
    [...agents.value].reverse().find((agent) => agent.status === "COMPLETED") ??
    agents.value[0],
);
const activeLabel = computed(() =>
  wrappingUp.value ? "결과 정리" : activeAgent.value?.label,
);
const activeMessage = computed(() => {
  if (wrappingUp.value) {
    return "에이전트 결과와 후속 작업을 확인해 최종 답변으로 정리하고 있어요.";
  }
  return activeAgent.value?.reason;
});

const groups = computed(() => {
  const values = new Map<number, PlannedAgent[]>();
  for (const agent of agents.value) {
    const group = values.get(agent.groupIndex) ?? [];
    group.push(agent);
    values.set(agent.groupIndex, group);
  }
  return [...values.entries()].map(([index, items]) => ({ index, items }));
});

const summaryTitle = computed(() => {
  const intent = props.plan?.intent;
  if (failed.value) return "요청 처리를 마치지 못했어요";
  if (wrappingUp.value) {
    return intent === "POSTING_ANALYSIS"
      ? "공고 해설을 마무리하고 있어요"
      : "답변을 마무리하고 있어요";
  }
  if (intent === "POSTING_ANALYSIS") {
    return allComplete.value ? "공고 내용 해설 완료" : "공고 내용을 해설하고 있어요";
  }
  if (intent === "INTERVIEW_PREP") {
    return allComplete.value ? "면접 준비 완료" : "면접 준비를 만들고 있어요";
  }
  if (intent === "COVER_LETTER") {
    return allComplete.value ? "자소서 초안 준비 완료" : "자소서 초안을 만들고 있어요";
  }
  return allComplete.value ? "JOBIS 답변 준비 완료" : "JOBIS가 답변을 준비하고 있어요";
});

function userLabel(agentId: string, fallback: string) {
  return {
    planner: "요청 이해",
    dispatch: "실행 계획",
    posting_fetch: "공고 가져오기",
    posting_analysis: "핵심 조건 정리",
    fit_analysis: "커리어 적합도 비교",
    career_chat: "진로 대화",
    preference_intake: "희망 조건 정리",
    resume_diagnosis: "경험 근거 확인",
    job_recommend: "대체 공고 탐색",
    interview_prep: "면접 질문 준비",
    coverletter_draft: "자소서 초안 작성",
    application_plan: "지원 계획 정리",
    roadmap_manager: "로드맵 해설",
    context_reader: "근거 읽기",
    response_writer: "답변 정리",
    llm_usage: "처리 기록",
  }[agentId] ?? fallback;
}

function color(agentId: string) {
  return {
    career_chat: "#ce82ff",
    preference_intake: "#9b6ddb",
    posting_fetch: "#1cb0f6",
    posting_analysis: "#1cb0f6",
    resume_diagnosis: "#58cc02",
    fit_analysis: "#00a99d",
    job_recommend: "#ffc800",
    interview_prep: "#a568cc",
    coverletter_draft: "#ff6b8a",
    application_plan: "#1899d6",
    roadmap_manager: "#58a700",
    context_reader: "#1cb0f6",
    response_writer: "#836dd0",
  }[agentId] ?? "#777777";
}

function statusLabel(status: PlannedAgent["status"]) {
  return {
    PENDING: "대기",
    RUNNING: "진행 중",
    COMPLETED: "완료",
    NEEDS_CONFIRMATION: "확인 필요",
    FAILED: "오류",
  }[status];
}
</script>

<template>
  <section v-if="agents.length" class="agent-execution-map" :class="{ compact }">
    <div class="agent-execution-map__summary" aria-live="polite">
      <span
        class="agent-execution-map__icon"
        :class="{ 'is-complete': allComplete, 'is-failed': failed }"
      >
        <CircleAlert v-if="failed" :size="18" />
        <Sparkles v-else-if="allComplete" :size="18" />
        <LoaderCircle v-else class="spin" :size="18" />
      </span>
      <div class="agent-execution-map__summary-copy">
        <strong>{{ summaryTitle }}</strong>
        <small>
          {{ activeLabel }}
          <template v-if="agents.length > 1"> · {{ completedCount }}/{{ agents.length }} 완료</template>
        </small>
      </div>
      <div
        class="agent-execution-map__trail"
        role="progressbar"
        :aria-valuenow="completedCount"
        :aria-valuemax="agents.length"
        aria-label="에이전트 실행 진행률"
      >
        <i
          v-for="agent in agents"
          :key="agent.runId"
          :class="`is-${agent.status.toLowerCase()}`"
          :style="{ '--agent-accent': color(agent.agentId) }"
        />
      </div>
    </div>

    <p v-if="activeMessage && !allComplete" class="agent-execution-map__message">
      {{ activeMessage }}
    </p>

    <details class="agent-execution-map__details">
      <summary>
        <span class="agent-execution-map__details-label">
          작업 과정 보기 · 에이전트 {{ agents.length }}개
        </span>
        <ChevronDown :size="16" />
      </summary>
      <ol>
        <template v-for="group in groups" :key="group.index">
          <li v-if="group.items.length > 1" class="agent-execution-map__parallel-label">
            동시에 실행
          </li>
          <li
            v-for="agent in group.items"
            :key="agent.runId"
            :class="`is-${agent.status.toLowerCase()}`"
            :style="{ '--agent-accent': color(agent.agentId) }"
          >
            <i />
            <div>
              <strong>{{ agent.label }}</strong>
              <small v-if="agent.reason">{{ agent.reason }}</small>
            </div>
            <span>{{ statusLabel(agent.status) }}</span>
          </li>
        </template>
      </ol>
    </details>
  </section>
</template>
