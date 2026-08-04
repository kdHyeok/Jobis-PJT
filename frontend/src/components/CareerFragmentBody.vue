<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
  description: string;
  detail?: Record<string, unknown> | null;
}>();

// 조각의 정형 칸 → 화면 라벨. **여기 없는 키는 보여주지 않는다** — detail 은 AI 가 채우는
// 자유 jsonb 라서, 화이트리스트가 없으면 내부 키·근거 원문이 그대로 화면으로 샌다.
// achievements 는 description 본문에 이미 줄로 들어 있어 칩으로 또 세지 않는다.
const LABELS: Record<string, string> = {
  period: "기간",
  teamSize: "팀 규모",
  role: "담당",
  projectType: "형태",
  employmentType: "고용형태",
  techStack: "기술",
};

function format(value: unknown): string {
  if (Array.isArray(value)) return value.map((item) => String(item).trim()).filter(Boolean).join(", ");
  return value == null ? "" : String(value).trim();
}

const chips = computed(() =>
  Object.entries(LABELS)
    .map(([key, label]) => ({ label, value: format(props.detail?.[key]) }))
    .filter((chip) => chip.value),
);
</script>

<template>
  <p class="fragment-body">{{ description || "추가 설명이 없습니다." }}</p>
  <ul v-if="chips.length" class="fragment-detail">
    <li v-for="chip in chips" :key="chip.label">
      <small>{{ chip.label }}</small> {{ chip.value }}
    </li>
  </ul>
</template>

<style>
/* 서술은 여러 줄로 들어온다(요약 + 성과 문장). 줄바꿈을 살려야 성과가 한 덩어리로 뭉치지 않는다. */
.fragment-body {
  white-space: pre-line;
}

.fragment-detail {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  margin: 6px 0 0;
  padding: 0;
  list-style: none;
}

.fragment-detail li {
  font-size: 13px;
  color: var(--text-primary);
}

.fragment-detail small {
  margin-right: 4px;
  color: var(--muted);
}
</style>
