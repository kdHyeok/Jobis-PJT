<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
  description: string;
  detail?: Record<string, unknown> | null;
}>();

const labels: Record<string, string> = {
  period: "기간",
  teamSize: "팀 규모",
  role: "담당",
  projectType: "형태",
  employmentType: "고용형태",
  techStack: "기술",
};

function format(value: unknown) {
  if (Array.isArray(value)) {
    return value.map((item) => String(item).trim()).filter(Boolean).join(", ");
  }
  return value == null ? "" : String(value).trim();
}

const chips = computed(() =>
  Object.entries(labels)
    .map(([key, label]) => ({ label, value: format(props.detail?.[key]) }))
    .filter((item) => item.value),
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

<style scoped>
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
