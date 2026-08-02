<script setup lang="ts">
import { Check, Clock3, Sparkles } from "@lucide/vue";
import { computed } from "vue";

import type { TodayTask } from "@/demo/roadmap-demo";

const props = defineProps<{
  tasks: TodayTask[];
}>();

defineEmits<{
  toggle: [taskId: number];
}>();

const doneCount = computed(() => props.tasks.filter((task) => task.done).length);
const earnedXp = computed(() =>
  props.tasks.filter((task) => task.done).reduce((sum, task) => sum + task.xp, 0),
);
</script>

<template>
  <section class="today-card">
    <header>
      <div>
        <span aria-label="오늘 할 일"><Sparkles :size="19" /></span>
        <h3>오늘 할 일</h3>
      </div>
      <strong>{{ doneCount }}/{{ tasks.length }}</strong>
    </header>

    <div class="today-progress">
      <i :style="{ width: `${(doneCount / tasks.length) * 100}%` }" />
    </div>

    <div class="today-list">
      <button
        v-for="task in tasks"
        :key="task.id"
        type="button"
        :class="{ done: task.done }"
        @click="$emit('toggle', task.id)"
      >
        <i class="today-check"><Check v-if="task.done" :size="14" :stroke-width="3" /></i>
        <span>
          <strong>{{ task.title }}</strong>
          <small>{{ task.meta }}</small>
          <em><Clock3 :size="11" /> {{ task.minutes }}분 · +{{ task.xp }} XP</em>
        </span>
      </button>
    </div>

    <footer>
      <span>오늘 획득</span>
      <strong>+{{ earnedXp }} XP</strong>
    </footer>
  </section>
</template>

<style scoped>
.today-card {
  padding: 20px;
  border: 1px solid #dce7e3;
  border-radius: 22px;
  background: #fff;
}

.today-card header,
.today-card footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.today-card header span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: #1489c1;
  font-size: 9px;
  font-weight: 900;
  letter-spacing: 0.11em;
}

.today-card h3 {
  margin: 5px 0 0;
  color: #2a4037;
  font-size: 20px;
}

.today-card header > strong {
  display: grid;
  width: 36px;
  height: 36px;
  place-items: center;
  border-radius: 50%;
  color: #1185bc;
  background: #e5f6fe;
  font-size: 11px;
}

.today-progress {
  height: 7px;
  margin: 15px 0;
  overflow: hidden;
  border-radius: 99px;
  background: #edf2ef;
}

.today-progress i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: #1cb0f6;
  transition: width 220ms ease;
}

.today-list {
  display: grid;
  gap: 8px;
}

.today-list button {
  display: grid;
  width: 100%;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 10px;
  padding: 11px;
  border: 1px solid #e1e8e5;
  border-radius: 14px;
  color: #30443c;
  background: #fff;
  cursor: pointer;
  text-align: left;
}

.today-list button:hover {
  border-color: #addbf1;
  background: #f8fcfe;
}

.today-list button.done {
  border-color: #c5e9ce;
  background: #f5fbf7;
}

.today-check {
  display: grid;
  width: 23px;
  height: 23px;
  place-items: center;
  border: 2px solid #cdd7d2;
  border-radius: 8px;
  color: #fff;
}

.done .today-check {
  border-color: #47b665;
  background: #58cc78;
}

.today-list span {
  display: grid;
  gap: 3px;
}

.today-list strong {
  font-size: 12px;
}

.today-list small {
  color: #82918b;
  font-size: 10px;
}

.today-list em {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 3px;
  color: #9a6b21;
  font-size: 10px;
  font-style: normal;
  font-weight: 800;
}

.today-card footer {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid #edf1ef;
  color: #82918b;
  font-size: 11px;
}

.today-card footer strong {
  color: #4ba864;
  font-size: 14px;
}
</style>
