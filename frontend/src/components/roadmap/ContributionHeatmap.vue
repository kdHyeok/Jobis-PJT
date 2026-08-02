<script setup lang="ts">
import { computed } from "vue";

const props = withDefaults(
  defineProps<{
    completedToday?: number;
  }>(),
  { completedToday: 1 },
);

const weeks = computed(() =>
  Array.from({ length: 14 }, (_, week) =>
    Array.from({ length: 7 }, (_, day) => {
      const seed = (week * 11 + day * 7 + week * day) % 13;
      const level = seed < 3 ? 0 : seed < 7 ? 1 : seed < 10 ? 2 : seed < 12 ? 3 : 4;
      return week === 13 && day === 3
        ? Math.min(4, props.completedToday + 1)
        : level;
    }),
  ),
);
</script>

<template>
  <section class="heatmap-card">
    <header>
      <div>
        <span>12주 활동</span>
        <h3>꾸준함이 실력을 만들고 있어요</h3>
      </div>
      <strong>🔥 9일 연속</strong>
    </header>

    <div class="heatmap-wrap">
      <div class="heatmap-days" aria-hidden="true">
        <span>월</span><span>수</span><span>금</span>
      </div>
      <div class="heatmap" aria-label="최근 14주 활동 기록">
        <div v-for="(week, weekIndex) in weeks" :key="weekIndex" class="heatmap__week">
          <i
            v-for="(level, dayIndex) in week"
            :key="dayIndex"
            :class="`level-${level}`"
            :title="`${weekIndex + 1}주차 ${dayIndex + 1}일 · 활동 ${level}단계`"
          />
        </div>
      </div>
    </div>

    <footer>
      <span>총 64개 활동</span>
      <span class="heatmap-legend">적음 <i /><i /><i /><i /><i /> 많음</span>
    </footer>
  </section>
</template>

<style scoped>
.heatmap-card {
  padding: 20px;
  border: 1px solid #dce7e3;
  border-radius: 22px;
  background: #fff;
}

.heatmap-card header,
.heatmap-card footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.heatmap-card header span {
  color: #3d9a72;
  font-size: 9px;
  font-weight: 900;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.heatmap-card h3 {
  margin: 5px 0 0;
  color: #2b4038;
  font-size: 17px;
  letter-spacing: -0.03em;
}

.heatmap-card header strong {
  padding: 7px 9px;
  border-radius: 10px;
  color: #b05c19;
  background: #fff3d9;
  font-size: 11px;
}

.heatmap-wrap {
  display: grid;
  grid-template-columns: 16px minmax(0, 1fr);
  gap: 7px;
  margin: 19px 0 14px;
}

.heatmap-days {
  display: flex;
  justify-content: space-around;
  flex-direction: column;
  color: #9aa7a1;
  font-size: 7px;
}

.heatmap {
  display: grid;
  grid-template-columns: repeat(14, minmax(7px, 1fr));
  gap: 4px;
}

.heatmap__week {
  display: grid;
  gap: 4px;
}

.heatmap i {
  width: 100%;
  aspect-ratio: 1;
  border-radius: 3px;
  background: #edf2ef;
}

.heatmap i.level-1 {
  background: #c7efd2;
}

.heatmap i.level-2 {
  background: #87d99d;
}

.heatmap i.level-3 {
  background: #4fbd6e;
}

.heatmap i.level-4 {
  background: #278f4a;
}

.heatmap-card footer {
  color: #85948e;
  font-size: 10px;
  font-weight: 800;
}

.heatmap-legend {
  display: flex;
  align-items: center;
  gap: 3px;
}

.heatmap-legend i {
  width: 8px;
  height: 8px;
  border-radius: 2px;
  background: #edf2ef;
}

.heatmap-legend i:nth-of-type(2) {
  background: #c7efd2;
}

.heatmap-legend i:nth-of-type(3) {
  background: #87d99d;
}

.heatmap-legend i:nth-of-type(4) {
  background: #4fbd6e;
}

.heatmap-legend i:nth-of-type(5) {
  background: #278f4a;
}
</style>
