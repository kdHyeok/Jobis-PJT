<script setup lang="ts">
import {
  ArrowLeftRight,
  CalendarDays,
  Check,
  Sparkles,
  Target,
  Trophy,
} from "@lucide/vue";
import { computed, ref } from "vue";

import ContributionHeatmap from "@/components/roadmap/ContributionHeatmap.vue";
import RoadmapNodeDrawer from "@/components/roadmap/RoadmapNodeDrawer.vue";
import RoadmapPath from "@/components/roadmap/RoadmapPath.vue";
import TodayTaskPanel from "@/components/roadmap/TodayTaskPanel.vue";
import {
  initialRoadmapNodes,
  initialTodayTasks,
  type RoadmapNode,
} from "@/demo/roadmap-demo";

const nodes = ref(initialRoadmapNodes.map((node) => ({ ...node })));
const tasks = ref(initialTodayTasks.map((task) => ({ ...task })));
const selectedNode = ref<RoadmapNode | null>(null);

const completedNodes = computed(
  () => nodes.value.filter((node) => node.state === "complete").length,
);
const completedToday = computed(() => tasks.value.filter((task) => task.done).length);
const progress = computed(() => Math.round((completedNodes.value / nodes.value.length) * 100));

function toggleTask(taskId: number) {
  const task = tasks.value.find((item) => item.id === taskId);
  if (task) task.done = !task.done;
}
</script>

<template>
  <main class="workspace vertical-map-page">
    <section class="vertical-map-hero">
      <div class="vertical-map-hero__copy">
        <span class="vertical-map-kicker"><Target :size="19" /> CAREER JOURNEY 02</span>
        <h1>별을 따라 내려가는<br />나의 합격 로드맵</h1>
        <p>하루의 작은 퀘스트가 별이 되고, 꾸준한 기록이 하나의 커리어 우주가 됩니다.</p>
        <RouterLink class="map-compare-link" :to="{ name: 'map' }">
          <ArrowLeftRight :size="17" /> 가로형 커리어 지도와 비교
        </RouterLink>
      </div>
      <div class="vertical-map-hero__mascot">
        <img src="/img/jobi-mascot.png" alt="로드맵을 안내하는 펭귄 자비" />
        <p><strong>자비의 한마디</strong>오늘은 SQL 행성에서<br />경험치 12 XP를 모아봐요!</p>
      </div>
      <div class="vertical-map-progress">
        <span>D-42</span>
        <strong>{{ progress }}%</strong>
        <small>전체 진행률</small>
        <div><i :style="{ width: `${progress}%` }" /></div>
      </div>
    </section>

    <section class="vertical-map-stats">
      <article>
        <span class="blue"><Sparkles :size="20" /></span>
        <p><small>공고 적합도</small><strong>68점</strong></p>
        <em>이번 주 +6</em>
      </article>
      <article>
        <span class="yellow"><Trophy :size="20" /></span>
        <p><small>누적 경험치</small><strong>1,280 XP</strong></p>
        <em>레벨 7</em>
      </article>
      <article>
        <span class="green"><CalendarDays :size="20" /></span>
        <p><small>이번 주 달성</small><strong>8 / 12</strong></p>
        <em><Check :size="13" /> 67%</em>
      </article>
    </section>

    <div class="vertical-map-layout">
      <RoadmapPath
        :nodes="nodes"
        :selected-id="selectedNode?.id ?? ''"
        @select="selectedNode = $event"
      />

      <aside class="vertical-map-rail">
        <TodayTaskPanel :tasks="tasks" @toggle="toggleTask" />
        <ContributionHeatmap :completed-today="completedToday" />
        <section class="jabi-tip-card">
          <img src="/img/jobi-mascot.png" alt="" />
          <div>
            <span>JABI'S TIP</span>
            <strong>9일 연속 성장 중!</strong>
            <p>오늘 퀘스트 하나만 완료해도 잔디가 한 단계 더 진해져요.</p>
          </div>
        </section>
      </aside>
    </div>

    <RoadmapNodeDrawer :node="selectedNode" @close="selectedNode = null" />
  </main>
</template>

<style scoped>
.vertical-map-page {
  width: min(100%, 1260px);
  color: #15336c;
}

.vertical-map-hero {
  position: relative;
  display: grid;
  min-height: 300px;
  grid-template-columns: minmax(0, 1fr) 330px 150px;
  align-items: center;
  gap: 22px;
  padding: 34px 38px;
  overflow: hidden;
  border: 1px solid #3268bd;
  border-radius: 30px;
  background:
    linear-gradient(rgba(31, 87, 173, 0.08) 1px, transparent 1px),
    linear-gradient(90deg, rgba(31, 87, 173, 0.08) 1px, transparent 1px),
    linear-gradient(rgba(5, 24, 65, 0.18), rgba(5, 24, 65, 0.18)),
    url("/img/roadmap-space-bg.png") center / cover;
  background-size: 38px 38px, 38px 38px, auto, cover;
  box-shadow: 0 12px 0 #b9cdf0, 0 28px 65px rgba(8, 37, 89, 0.19);
}

.vertical-map-hero__copy,
.vertical-map-hero__mascot,
.vertical-map-progress {
  position: relative;
  z-index: 1;
}

.vertical-map-kicker {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #82c5ff;
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0.12em;
}

.vertical-map-hero h1 {
  margin: 12px 0 10px;
  color: #fff;
  font-size: clamp(36px, 4.1vw, 56px);
  line-height: 1.08;
  letter-spacing: -0.055em;
}

.vertical-map-hero__copy > p {
  max-width: 590px;
  margin: 0;
  color: #c4dcff;
  font-size: 15px;
  line-height: 1.65;
}

.map-compare-link {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-top: 20px;
  padding: 10px 13px;
  border: 1px solid rgba(140, 190, 255, 0.42);
  border-radius: 12px;
  color: #e0eeff;
  background: rgba(8, 33, 83, 0.66);
  text-decoration: none;
  font-size: 12px;
  font-weight: 850;
}

.vertical-map-hero__mascot {
  display: flex;
  align-items: flex-end;
}

.vertical-map-hero__mascot img {
  width: 132px;
  height: 152px;
  object-fit: contain;
  filter: drop-shadow(0 12px 18px rgba(0, 10, 40, 0.38));
}

.vertical-map-hero__mascot p {
  min-width: 198px;
  margin: 0 0 24px -8px;
  padding: 14px 16px;
  border: 2px solid #d9e7ff;
  border-radius: 18px 18px 18px 5px;
  color: #3d5378;
  background: #fff;
  font-size: 12px;
  line-height: 1.5;
  box-shadow: 0 9px 22px rgba(0, 12, 43, 0.24);
}

.vertical-map-hero__mascot strong {
  display: block;
  margin-bottom: 3px;
  color: #185bca;
}

.vertical-map-progress {
  display: grid;
  min-height: 150px;
  place-items: center;
  align-content: center;
  padding: 18px;
  border: 1px solid rgba(145, 190, 255, 0.4);
  border-bottom: 6px solid #3176df;
  border-radius: 24px;
  color: #fff;
  background: rgba(5, 27, 73, 0.75);
  backdrop-filter: blur(12px);
}

.vertical-map-progress > span {
  color: #ffd43e;
  font-size: 13px;
  font-weight: 900;
}

.vertical-map-progress > strong {
  margin-top: 3px;
  font-size: 38px;
}

.vertical-map-progress > small {
  color: #a9c8f8;
}

.vertical-map-progress > div {
  width: 100%;
  height: 8px;
  margin-top: 12px;
  overflow: hidden;
  border-radius: 99px;
  background: #173a78;
}

.vertical-map-progress i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #2b7bf2, #ffd43e);
}

.vertical-map-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
  margin: 28px 0 18px;
}

.vertical-map-stats article {
  display: grid;
  min-height: 90px;
  grid-template-columns: 48px 1fr auto;
  align-items: center;
  gap: 12px;
  padding: 16px 18px;
  border: 1px solid #cfdef6;
  border-bottom: 6px solid #d9e5f7;
  border-radius: 20px;
  background: #fff;
}

.vertical-map-stats article > span {
  display: grid;
  width: 46px;
  height: 46px;
  place-items: center;
  border-radius: 15px;
}

.vertical-map-stats .blue { color: #1761d7; background: #e7f1ff; }
.vertical-map-stats .yellow { color: #8a6700; background: #fff3bd; }
.vertical-map-stats .green { color: #18744b; background: #e3f7ec; }

.vertical-map-stats p {
  display: grid;
  gap: 3px;
  margin: 0;
}

.vertical-map-stats small { color: #7183a3; font-size: 11px; }
.vertical-map-stats strong { color: #183871; font-size: 20px; }
.vertical-map-stats em {
  display: flex;
  align-items: center;
  gap: 3px;
  color: #1760d6;
  font-size: 11px;
  font-style: normal;
  font-weight: 850;
}

.vertical-map-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  align-items: start;
  gap: 18px;
}

.vertical-map-page :deep(.roadmap-path) {
  border-color: #315a9c;
  background:
    linear-gradient(rgba(68, 132, 227, 0.07) 1px, transparent 1px),
    linear-gradient(90deg, rgba(68, 132, 227, 0.07) 1px, transparent 1px),
    linear-gradient(rgba(5, 22, 60, 0.3), rgba(5, 22, 60, 0.3)),
    url("/img/roadmap-space-bg.png") center / cover;
  background-size: 38px 38px, 38px 38px, auto, cover;
  box-shadow: 0 12px 0 #b9cdef, 0 28px 60px rgba(11, 42, 97, 0.18);
}

.vertical-map-page :deep(.roadmap-path h2),
.vertical-map-page :deep(.roadmap-node__copy strong) {
  color: #fff;
}

.vertical-map-page :deep(.roadmap-path p),
.vertical-map-page :deep(.roadmap-node__copy span) {
  color: #aac7ef;
}

.vertical-map-page :deep(.roadmap-path__legend),
.vertical-map-page :deep(.roadmap-node) {
  border-color: rgba(119, 168, 239, 0.35);
  background: rgba(7, 29, 73, 0.84);
  backdrop-filter: blur(10px);
}

.vertical-map-page :deep(.roadmap-node-row--current .roadmap-node) {
  border-color: #68b8ff;
  background: rgba(8, 44, 105, 0.92);
}

.vertical-map-page :deep(.roadmap-node-row--available .roadmap-node) {
  border-color: #ffd94e;
}

.vertical-map-page :deep(.roadmap-node-row--locked .roadmap-node) {
  background: rgba(11, 30, 66, 0.75);
}

.vertical-map-page :deep(.roadmap-node__copy small) {
  color: #71b9ff;
}

.vertical-map-rail {
  position: sticky;
  top: 82px;
  display: grid;
  gap: 16px;
}

.vertical-map-rail :deep(.heatmap-card),
.vertical-map-rail :deep(.today-card) {
  border-color: #cadbf7;
  background: linear-gradient(145deg, #fff, #f3f7ff);
  box-shadow: 0 7px 0 #e0e9f8;
}

.vertical-map-rail :deep(.today-card h3),
.vertical-map-rail :deep(.heatmap-card h3) {
  color: #163a79;
}

.vertical-map-rail :deep(.today-card header span),
.vertical-map-rail :deep(.heatmap-card header span) {
  color: #1a61d5;
}

.vertical-map-rail :deep(.today-card header > strong) {
  color: #165dcc;
  background: #e6efff;
}

.vertical-map-rail :deep(.today-progress) {
  background: #dfe9f9;
}

.vertical-map-rail :deep(.today-progress i) {
  background: linear-gradient(90deg, #1b60dc, #55a9ff);
}

.vertical-map-rail :deep(.today-list button) {
  border-color: #d8e4f7;
  color: #274676;
  background: #fff;
}

.vertical-map-rail :deep(.today-list button:hover),
.vertical-map-rail :deep(.today-list button.done) {
  border-color: #9bbcf2;
  background: #edf4ff;
}

.vertical-map-rail :deep(.done .today-check) {
  border-color: #1d64d8;
  background: #2874e8;
}

.vertical-map-rail :deep(.today-list em),
.vertical-map-rail :deep(.today-card footer strong) {
  color: #1a5dcc;
}

.vertical-map-rail :deep(.heatmap-card header strong) {
  color: #174fba;
  background: #e7f0ff;
}

.vertical-map-rail :deep(.heatmap i),
.vertical-map-rail :deep(.heatmap-legend i) {
  background: #e8eef8;
}

.vertical-map-rail :deep(.heatmap i.level-1),
.vertical-map-rail :deep(.heatmap-legend i:nth-of-type(2)) {
  background: #c9dcfb;
}

.vertical-map-rail :deep(.heatmap i.level-2),
.vertical-map-rail :deep(.heatmap-legend i:nth-of-type(3)) {
  background: #8db8f5;
}

.vertical-map-rail :deep(.heatmap i.level-3),
.vertical-map-rail :deep(.heatmap-legend i:nth-of-type(4)) {
  background: #4f8ee8;
}

.vertical-map-rail :deep(.heatmap i.level-4),
.vertical-map-rail :deep(.heatmap-legend i:nth-of-type(5)) {
  background: #1a5bc8;
}

.jabi-tip-card {
  display: grid;
  min-height: 150px;
  grid-template-columns: 108px 1fr;
  align-items: center;
  gap: 5px;
  padding: 15px;
  overflow: hidden;
  border: 1px solid #b9d1fa;
  border-bottom: 6px solid #5b94eb;
  border-radius: 22px;
  background: linear-gradient(135deg, #edf4ff, #fff);
}

.jabi-tip-card img {
  width: 105px;
  height: 120px;
  object-fit: contain;
}

.jabi-tip-card span {
  color: #1b60d5;
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0.1em;
}

.jabi-tip-card strong {
  display: block;
  margin: 6px 0;
  color: #173873;
  font-size: 16px;
}

.jabi-tip-card p {
  margin: 0;
  color: #66799a;
  font-size: 12px;
  line-height: 1.55;
}

@media (max-width: 1080px) {
  .vertical-map-hero {
    grid-template-columns: 1fr 280px;
  }

  .vertical-map-progress {
    display: none;
  }

  .vertical-map-layout {
    grid-template-columns: 1fr;
  }

  .vertical-map-rail {
    position: static;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .vertical-map-hero {
    display: block;
    padding: 26px 22px;
  }

  .vertical-map-hero__mascot {
    display: none;
  }

  .vertical-map-stats,
  .vertical-map-rail {
    grid-template-columns: 1fr;
  }
}
</style>
