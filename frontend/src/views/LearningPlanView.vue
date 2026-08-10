<script setup lang="ts">
import { CalendarDays, Check, ChevronLeft, ChevronRight, Clock3, ListTodo } from "@lucide/vue";
import { computed, ref } from "vue";
import { useRouter } from "vue-router";

import { learningPlan, type LearningPlanItem } from "@/learning-plan";

const router = useRouter();
const mode = ref<"WEEK" | "MONTH">("WEEK");
const cursor = ref(new Date());
const selectedDay = ref<string | null>(null);

function iso(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function addDays(date: Date, days: number) {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

const weekStart = computed(() => addDays(cursor.value, -((cursor.value.getDay() + 6) % 7)));
const weekDays = computed(() => Array.from({ length: 7 }, (_, index) => addDays(weekStart.value, index)));
const monthDays = computed(() => {
  const first = new Date(cursor.value.getFullYear(), cursor.value.getMonth(), 1);
  const start = addDays(first, -((first.getDay() + 6) % 7));
  return Array.from({ length: 42 }, (_, index) => addDays(start, index));
});
const visibleDays = computed(() => mode.value === "WEEK" ? weekDays.value : monthDays.value);
const selectedItems = computed(() => selectedDay.value ? itemsForDay(selectedDay.value) : []);

function dateRange(item: LearningPlanItem) {
  const start = new Date(`${item.startDate}T00:00:00`);
  const end = new Date(`${item.endDate}T00:00:00`);
  return Math.max(1, Math.round((end.getTime() - start.getTime()) / 86400000) + 1);
}

function minutesForDay(item: LearningPlanItem) {
  return Math.max(15, Math.ceil((item.estimatedMinutes - item.spentMinutes) / dateRange(item) / 15) * 15);
}

function itemsForDay(day: string) {
  return learningPlan.items.value.filter((item) => !item.completed && item.startDate <= day && item.endDate >= day);
}

function dayMinutes(day: string) {
  return itemsForDay(day).reduce((sum, item) => sum + minutesForDay(item), 0);
}

function move(direction: number) {
  cursor.value = mode.value === "WEEK"
    ? addDays(cursor.value, direction * 7)
    : new Date(cursor.value.getFullYear(), cursor.value.getMonth() + direction, 1);
}

function formatMinutes(minutes: number) {
  if (minutes < 60) return `${minutes}분`;
  return `${Math.floor(minutes / 60)}시간${minutes % 60 ? ` ${minutes % 60}분` : ""}`;
}

function subjectTone(item: LearningPlanItem) {
  let hash = 0;
  for (const char of item.canonicalKey || item.title) hash = ((hash << 5) - hash + char.charCodeAt(0)) | 0;
  return `tone-${Math.abs(hash) % 6}`;
}
</script>

<template>
  <main class="workspace learning-plan-workspace">
    <Teleport to="#app-topbar-center"><h1 class="app-page-title learning-page-title">학습 플랜</h1></Teleport>
    <section class="learning-plan-hero">
      <div>
        <p>LEARNING PLAN</p>
        <h1>이번 주 학습 플랜</h1>
        <span>로드맵에서 선택한 학습을 하루 단위로 나누고, 실제 학습 시간에 맞춰 남은 일정을 조정합니다.</span>
      </div>
      <div class="learning-view-toggle" role="group" aria-label="학습 플랜 보기 방식">
        <button :class="{ active: mode === 'WEEK' }" type="button" @click="mode = 'WEEK'">주간</button>
        <button :class="{ active: mode === 'MONTH' }" type="button" @click="mode = 'MONTH'">월간</button>
      </div>
    </section>

    <section class="learning-calendar-card">
      <header>
        <button type="button" aria-label="이전 기간" @click="move(-1)"><ChevronLeft :size="19" /></button>
        <h2>{{ cursor.getFullYear() }}년 {{ cursor.getMonth() + 1 }}월</h2>
        <button type="button" aria-label="다음 기간" @click="move(1)"><ChevronRight :size="19" /></button>
      </header>
      <div class="learning-calendar-grid" :class="`is-${mode.toLowerCase()}`">
        <button
          v-for="day in visibleDays"
          :key="iso(day)"
          type="button"
          :class="{ selected: selectedDay === iso(day), muted: mode === 'MONTH' && day.getMonth() !== cursor.getMonth() }"
          @click="selectedDay = iso(day)"
        >
          <span>{{ day.getDate() }} <small>{{ ['일','월','화','수','목','금','토'][day.getDay()] }}</small></span>
          <template v-if="mode === 'WEEK'">
            <article v-for="item in itemsForDay(iso(day))" :key="item.id" :class="subjectTone(item)" @click.stop="router.push({ name: 'learning', params: { planId: item.id } })">
              <strong>{{ item.title }}</strong>
              <em><Clock3 :size="13" /> {{ formatMinutes(minutesForDay(item)) }}</em>
              <small>{{ item.modules[0]?.title ?? '학습 범위 정리' }}</small>
            </article>
          </template>
          <div v-else-if="itemsForDay(iso(day)).length" class="month-learning-summary">
            <strong>{{ itemsForDay(iso(day)).length }}개</strong>
            <small>{{ formatMinutes(dayMinutes(iso(day))) }}</small>
          </div>
        </button>
      </div>
    </section>

    <section v-if="!learningPlan.items.value.length" class="learning-plan-empty">
      <CalendarDays :size="30" />
      <h2>등록한 학습 일정이 없습니다</h2>
      <p>커리어 지도에서 학습할 역량을 선택하고 기간을 등록해 주세요.</p>
      <button class="press-button press-button--primary" type="button" @click="router.push({ name: 'map' })">커리어 지도에서 선택</button>
    </section>

    <div v-if="selectedDay" class="learning-day-backdrop" @click="selectedDay = null" />
    <aside v-if="selectedDay" class="learning-day-drawer" role="dialog" aria-modal="true">
      <header><div><small>{{ selectedDay }}</small><h2>오늘의 학습</h2></div><button type="button" @click="selectedDay = null">닫기</button></header>
      <article v-for="item in selectedItems" :key="item.id" :class="subjectTone(item)">
        <span><ListTodo :size="18" /></span>
        <div><strong>{{ item.title }}</strong><small>예상 {{ formatMinutes(minutesForDay(item)) }} · 누적 {{ formatMinutes(item.spentMinutes) }}</small></div>
        <button type="button" @click="router.push({ name: 'learning', params: { planId: item.id } })">학습 열기</button>
      </article>
      <div v-if="!selectedItems.length" class="learning-day-empty"><Check :size="24" /><p>이날 예정된 학습이 없습니다.</p></div>
    </aside>
  </main>
</template>
