<script setup lang="ts">
import {
  Activity,
  Bell,
  BriefcaseBusiness,
  CalendarDays,
  ChevronDown,
  House,
  Map,
  MessageCircle,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  Sparkles,
  Target,
  Trophy,
} from "@lucide/vue";
import { computed, ref } from "vue";
import { RouterLink } from "vue-router";

import AiReplanPanel from "@/components/roadmap/AiReplanPanel.vue";
import ContributionHeatmap from "@/components/roadmap/ContributionHeatmap.vue";
import RoadmapNodeDrawer from "@/components/roadmap/RoadmapNodeDrawer.vue";
import RoadmapPath from "@/components/roadmap/RoadmapPath.vue";
import TodayTaskPanel from "@/components/roadmap/TodayTaskPanel.vue";
import DemoActivityPanel from "@/components/preview/DemoActivityPanel.vue";
import DemoChatPanel from "@/components/preview/DemoChatPanel.vue";
import DemoHomePanel from "@/components/preview/DemoHomePanel.vue";
import DemoPostingsPanel from "@/components/preview/DemoPostingsPanel.vue";
import {
  initialRoadmapNodes,
  initialTodayTasks,
  type RoadmapNode,
} from "@/demo/roadmap-demo";

const nodes = ref(initialRoadmapNodes.map((node) => ({ ...node })));
const tasks = ref(initialTodayTasks.map((task) => ({ ...task })));
const selectedNode = ref<RoadmapNode | null>(null);
const aiApplied = ref(false);
const sidebarCollapsed = ref(false);
const activePage = ref<"home" | "chat" | "postings" | "roadmap" | "activity">("roadmap");

const completedNodes = computed(
  () => nodes.value.filter((node) => node.state === "complete").length,
);
const progress = computed(() => Math.round((completedNodes.value / nodes.value.length) * 100));
const completedToday = computed(() => tasks.value.filter((task) => task.done).length);
const readiness = computed(() => 62 + completedToday.value * 2 + (aiApplied.value ? 4 : 0));

function toggleTask(taskId: number) {
  const task = tasks.value.find((item) => item.id === taskId);
  if (task) task.done = !task.done;
}

function applyAiPlan() {
  aiApplied.value = true;
  const project = nodes.value.find((node) => node.id === "project");
  if (project) {
    project.state = "current";
    project.subtitle = "AI 추천 · 적합도 +8점";
  }
  const sql = nodes.value.find((node) => node.id === "sql");
  if (sql) sql.state = "available";
}
</script>

<template>
  <div class="roadmap-demo" :class="{ 'sidebar-collapsed': sidebarCollapsed }">
    <aside class="demo-sidebar">
      <RouterLink class="demo-brand" to="/roadmap-preview">
        <span>J</span>
        <strong>J.O.B.I.S</strong>
      </RouterLink>
      <button
        class="sidebar-collapse-button"
        type="button"
        :aria-label="sidebarCollapsed ? '사이드바 펼치기' : '사이드바 접기'"
        :title="sidebarCollapsed ? '사이드바 펼치기' : '사이드바 접기'"
        @click="sidebarCollapsed = !sidebarCollapsed"
      >
        <PanelLeftOpen v-if="sidebarCollapsed" :size="18" />
        <PanelLeftClose v-else :size="18" />
      </button>
      <nav aria-label="미리보기 메뉴">
        <button type="button" :class="{ active: activePage === 'home' }" @click="activePage = 'home'"><House :size="19" /><span>홈</span></button>
        <button type="button" :class="{ active: activePage === 'chat' }" @click="activePage = 'chat'"><MessageCircle :size="19" /><span>AI 대화</span></button>
        <button type="button" :class="{ active: activePage === 'postings' }" @click="activePage = 'postings'"><BriefcaseBusiness :size="19" /><span>채용 공고</span></button>
        <button type="button" :class="{ active: activePage === 'roadmap' }" @click="activePage = 'roadmap'"><Map :size="19" /><span>나의 로드맵</span></button>
        <button type="button" :class="{ active: activePage === 'activity' }" @click="activePage = 'activity'"><Activity :size="19" /><span>활동 기록</span></button>
      </nav>
      <div class="demo-sidebar__profile">
        <span>박</span>
        <p><strong>박준영</strong><small>디지털·IT 준비 중</small></p>
        <Settings :size="17" />
      </div>
    </aside>

    <div class="demo-content">
      <header class="demo-topbar">
        <button type="button">
          <span>목표 공고</span>
          광주은행 디지털·IT
          <ChevronDown :size="14" />
        </button>
        <div>
          <span class="demo-streak">🔥 9일 연속</span>
          <button class="demo-bell" type="button" aria-label="알림"><Bell :size="18" /></button>
          <span class="demo-avatar">박</span>
        </div>
      </header>

      <main :class="{ 'space-page': activePage === 'roadmap' }">
        <DemoHomePanel v-if="activePage === 'home'" @navigate="activePage = $event" />
        <DemoChatPanel v-else-if="activePage === 'chat'" />
        <DemoPostingsPanel v-else-if="activePage === 'postings'" />
        <DemoActivityPanel v-else-if="activePage === 'activity'" />
        <template v-else>
        <section class="demo-hero">
          <div>
            <span class="demo-hero__kicker" aria-label="커리어 목표"><Target :size="23" /></span>
            <h1>광주은행 디지털·IT<br />합격 로드맵</h1>
            <p>현재 경험과 공고 마감일을 기준으로 AI가 계속 조정하는 준비 경로예요.</p>
          </div>

          <div class="demo-goal-card">
            <img class="demo-goal-mascot" src="/img/jobi-mascot.png" alt="" />
            <span>D-42</span>
            <p><small>전체 진행률</small><strong>{{ progress }}%</strong></p>
            <div><i :style="{ width: `${progress}%` }" /></div>
            <em>현재 단계 · {{ aiApplied ? "금융 API 미니 프로젝트" : "SQL 실전 역량" }}</em>
          </div>
        </section>

        <section class="demo-stats">
          <article>
            <span class="blue"><Sparkles :size="18" /></span>
            <p><small>공고 적합도</small><strong>{{ readiness }}점</strong></p>
            <em>이번 주 +{{ readiness - 62 }}</em>
          </article>
          <article>
            <span class="green"><Trophy :size="18" /></span>
            <p><small>누적 경험치</small><strong>1,280 XP</strong></p>
            <em>레벨 7</em>
          </article>
          <article>
            <span class="yellow"><CalendarDays :size="18" /></span>
            <p><small>이번 주 달성</small><strong>8 / 12</strong></p>
            <em>67%</em>
          </article>
        </section>

        <div class="demo-grid">
          <RoadmapPath
            :nodes="nodes"
            :selected-id="selectedNode?.id ?? ''"
            @select="selectedNode = $event"
          />

          <aside class="demo-rail">
            <TodayTaskPanel :tasks="tasks" @toggle="toggleTask" />
            <AiReplanPanel :applied="aiApplied" @apply="applyAiPlan" />
            <ContributionHeatmap :completed-today="completedToday" />
          </aside>
        </div>
        </template>
      </main>
    </div>

    <RoadmapNodeDrawer :node="selectedNode" @close="selectedNode = null" />
  </div>
</template>

<style scoped>
.roadmap-demo {
  --demo-ink: #273c35;
  min-height: 100vh;
  color: var(--demo-ink);
  background:
    radial-gradient(circle at 65% 0, rgba(88, 204, 120, 0.09), transparent 26%),
    #f5f8f6;
  font-family: Pretendard, system-ui, sans-serif;
}

.demo-sidebar {
  position: fixed;
  z-index: 20;
  top: 0;
  bottom: 0;
  left: 0;
  display: flex;
  width: 224px;
  flex-direction: column;
  padding: 24px 17px 18px;
  border-right: 1px solid #dde6e2;
  background: rgba(255, 255, 255, 0.96);
  transition: width 220ms ease;
}

.demo-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  color: #2b463b;
  text-decoration: none;
}

.demo-brand > span {
  display: grid;
  width: 38px;
  height: 38px;
  place-items: center;
  border-radius: 13px;
  color: #fff;
  background: #58cc78;
  box-shadow: 0 5px 0 #38a858;
  font-size: 19px;
  font-weight: 950;
}

.demo-brand strong {
  font-size: 18px;
  letter-spacing: -0.03em;
}

.sidebar-collapse-button {
  position: absolute;
  top: 28px;
  right: -15px;
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border: 1px solid #d9e4df;
  border-radius: 10px;
  color: #6c7f76;
  background: #fff;
  box-shadow: 0 6px 16px rgba(44, 72, 62, 0.1);
  cursor: pointer;
  transition: color 140ms ease, background 140ms ease, transform 140ms ease;
}

.sidebar-collapse-button:hover {
  color: #218b5d;
  background: #f0faf4;
  transform: scale(1.04);
}

.demo-sidebar nav {
  display: grid;
  gap: 6px;
  margin-top: 42px;
}

.demo-sidebar nav button {
  display: flex;
  width: 100%;
  align-items: center;
  gap: 11px;
  padding: 12px 13px;
  border: 0;
  border-radius: 13px;
  color: #71827b;
  background: transparent;
  cursor: pointer;
  text-align: left;
  font-size: 13px;
  font-weight: 800;
}

.demo-sidebar nav button:hover {
  background: #f3f7f5;
}

.demo-sidebar nav button.active {
  color: #188a4b;
  background: #e9f8ee;
  box-shadow: inset 4px 0 #58cc78;
}

.demo-sidebar__profile {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 9px;
  margin-top: auto;
  padding: 11px;
  border-radius: 15px;
  background: #f3f7f5;
}

.demo-sidebar__profile > span,
.demo-avatar {
  display: grid;
  width: 33px;
  height: 33px;
  place-items: center;
  border-radius: 11px;
  color: #fff;
  background: #6174d9;
  font-size: 10px;
  font-weight: 900;
}

.demo-sidebar__profile p {
  min-width: 0;
  margin: 0;
}

.demo-sidebar__profile strong,
.demo-sidebar__profile small {
  display: block;
}

.demo-sidebar__profile strong {
  font-size: 12px;
}

.demo-sidebar__profile small {
  margin-top: 2px;
  overflow: hidden;
  color: #899891;
  font-size: 9px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.demo-content {
  min-height: 100vh;
  margin-left: 224px;
  transition: margin-left 220ms ease;
}

.roadmap-demo.sidebar-collapsed .demo-sidebar {
  width: 82px;
  padding-right: 12px;
  padding-left: 12px;
}

.roadmap-demo.sidebar-collapsed .demo-content {
  margin-left: 82px;
}

.roadmap-demo.sidebar-collapsed .demo-brand {
  justify-content: center;
}

.roadmap-demo.sidebar-collapsed .demo-brand strong,
.roadmap-demo.sidebar-collapsed .demo-sidebar nav button span,
.roadmap-demo.sidebar-collapsed .demo-sidebar__profile p,
.roadmap-demo.sidebar-collapsed .demo-sidebar__profile > svg {
  display: none;
}

.roadmap-demo.sidebar-collapsed .demo-sidebar nav button {
  justify-content: center;
  padding-right: 8px;
  padding-left: 8px;
}

.roadmap-demo.sidebar-collapsed .demo-sidebar__profile {
  display: flex;
  justify-content: center;
  padding: 8px;
}

.demo-topbar {
  position: sticky;
  z-index: 10;
  top: 0;
  display: flex;
  height: 68px;
  align-items: center;
  justify-content: space-between;
  padding: 0 34px;
  border-bottom: 1px solid #dde6e2;
  background: rgba(255, 255, 255, 0.88);
  backdrop-filter: blur(16px);
}

.demo-topbar button {
  border: 0;
  color: #40564d;
  background: transparent;
  cursor: pointer;
  font: inherit;
  font-size: 10px;
  font-weight: 850;
}

.demo-topbar > button {
  display: flex;
  align-items: center;
  gap: 8px;
}

.demo-topbar > button span {
  color: #91a099;
  font-size: 8px;
}

.demo-topbar > div {
  display: flex;
  align-items: center;
  gap: 10px;
}

.demo-streak {
  padding: 7px 10px;
  border-radius: 10px;
  color: #a25a1b;
  background: #fff1d7;
  font-size: 9px;
  font-weight: 900;
}

.demo-bell {
  display: grid;
  width: 35px;
  height: 35px;
  place-items: center;
  border-radius: 11px !important;
  background: #f1f5f3 !important;
}

.demo-content main {
  width: min(100%, 1280px);
  margin: 0 auto;
  padding: 34px;
}

.demo-hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  align-items: stretch;
  gap: 24px;
  padding: 34px;
  overflow: hidden;
  border: 1px solid #cfe4da;
  border-radius: 28px;
  background:
    radial-gradient(circle at 92% 0, rgba(28, 176, 246, 0.22), transparent 28%),
    radial-gradient(circle at 25% 120%, rgba(88, 204, 120, 0.2), transparent 36%),
    #fff;
  box-shadow: 0 18px 60px rgba(51, 87, 73, 0.08);
}

.demo-hero__kicker {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #248f65;
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0.11em;
}

.demo-hero h1 {
  margin: 13px 0 10px;
  color: #263f35;
  font-size: clamp(30px, 4vw, 48px);
  line-height: 1.08;
  letter-spacing: -0.065em;
}

.demo-hero > div > p {
  margin: 0;
  color: #74877f;
  font-size: 12px;
}

.demo-goal-card {
  display: grid;
  align-content: center;
  padding: 22px;
  border: 1px solid rgba(255, 255, 255, 0.8);
  border-radius: 22px;
  background: rgba(246, 252, 249, 0.82);
  backdrop-filter: blur(12px);
}

.demo-goal-card > span {
  width: max-content;
  padding: 6px 9px;
  border-radius: 9px;
  color: #fff;
  background: #ff8a4c;
  font-size: 10px;
  font-weight: 900;
}

.demo-goal-card p {
  display: flex;
  align-items: end;
  justify-content: space-between;
  margin: 18px 0 8px;
}

.demo-goal-card small,
.demo-goal-card strong {
  display: block;
}

.demo-goal-card small {
  color: #7c8e86;
  font-size: 9px;
}

.demo-goal-card strong {
  color: #258c60;
  font-size: 27px;
}

.demo-goal-card > div {
  height: 9px;
  overflow: hidden;
  border-radius: 99px;
  background: #dce8e2;
}

.demo-goal-card > div i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #58cc78, #1cb0f6);
}

.demo-goal-card em {
  margin-top: 10px;
  color: #6d8178;
  font-size: 8px;
  font-style: normal;
  font-weight: 800;
}

.demo-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 13px;
  margin: 17px 0 22px;
}

.demo-stats article {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 11px;
  padding: 16px;
  border: 1px solid #dde7e2;
  border-radius: 18px;
  background: #fff;
}

.demo-stats article > span {
  display: grid;
  width: 39px;
  height: 39px;
  place-items: center;
  border-radius: 13px;
}

.demo-stats .blue {
  color: #168ac1;
  background: #e4f5fd;
}

.demo-stats .green {
  color: #2b9850;
  background: #e6f7eb;
}

.demo-stats .yellow {
  color: #a87a0c;
  background: #fff5d8;
}

.demo-stats p {
  margin: 0;
}

.demo-stats small,
.demo-stats strong {
  display: block;
}

.demo-stats small {
  color: #87968f;
  font-size: 8px;
}

.demo-stats strong {
  margin-top: 3px;
  font-size: 14px;
}

.demo-stats em {
  color: #369159;
  font-size: 8px;
  font-style: normal;
  font-weight: 900;
}

.demo-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 330px;
  align-items: start;
  gap: 20px;
}

.demo-rail {
  position: sticky;
  top: 88px;
  display: grid;
  gap: 14px;
}

@media (max-width: 1080px) {
  .demo-grid {
    grid-template-columns: 1fr;
  }

  .demo-rail {
    position: static;
    grid-template-columns: 1fr 1fr;
  }

  .demo-rail > :last-child {
    grid-column: 1 / -1;
  }
}

@media (max-width: 820px) {
  .demo-sidebar {
    position: fixed;
    top: auto;
    right: 0;
    bottom: 0;
    width: 100%;
    height: 68px;
    padding: 6px;
    border-top: 1px solid #dde6e2;
    border-right: 0;
  }

  .sidebar-collapse-button {
    display: none;
  }

  .roadmap-demo.sidebar-collapsed .demo-sidebar {
    width: 100%;
    padding: 6px;
  }

  .roadmap-demo.sidebar-collapsed .demo-content {
    margin-left: 0;
  }

  .roadmap-demo.sidebar-collapsed .demo-sidebar nav button span {
    display: inline;
  }

  .demo-brand,
  .demo-sidebar__profile {
    display: none;
  }

  .demo-sidebar nav {
    display: grid;
    height: 100%;
    grid-template-columns: repeat(5, 1fr);
    gap: 2px;
    margin: 0;
  }

  .demo-sidebar nav button {
    justify-content: center;
    flex-direction: column;
    gap: 3px;
    padding: 3px;
    font-size: 7px;
  }

  .demo-sidebar nav button.active {
    box-shadow: inset 0 3px #58cc78;
  }

  .demo-content {
    margin: 0;
    padding-bottom: 68px;
  }

  .demo-topbar {
    height: 58px;
    padding: 0 16px;
  }

  .demo-streak {
    display: none;
  }

  .demo-content main {
    padding: 18px 14px 28px;
  }

  .demo-hero {
    grid-template-columns: 1fr;
    padding: 24px;
  }

  .demo-stats {
    grid-template-columns: 1fr;
  }

  .demo-rail {
    grid-template-columns: 1fr;
  }

  .demo-rail > :last-child {
    grid-column: auto;
  }
}

/* Preview-wide readability pass */
.demo-content :deep(.home-preview .home-summary small),
.demo-content :deep(.home-preview .home-card p),
.demo-content :deep(.home-preview .home-card header small),
.demo-content :deep(.home-preview .recent-postings p) {
  font-size: 10px;
}

.demo-content :deep(.home-preview .home-card strong) {
  font-size: 12px;
}

.demo-content :deep(.home-preview .ai-callout strong) {
  font-size: 15px;
}

.demo-content :deep(.home-preview .ai-callout p),
.demo-content :deep(.home-preview .home-welcome p) {
  font-size: 12px;
  line-height: 1.55;
}

.demo-content :deep(.chat-preview aside strong) {
  font-size: 12px;
}

.demo-content :deep(.chat-preview aside p),
.demo-content :deep(.chat-preview aside small) {
  font-size: 10px;
}

.demo-content :deep(.chat-preview .message-stream article p) {
  font-size: 12px;
  line-height: 1.7;
}

.demo-content :deep(.chat-preview .analysis-card strong) {
  font-size: 11px;
}

.demo-content :deep(.chat-preview .analysis-card small),
.demo-content :deep(.chat-preview .chat-context small),
.demo-content :deep(.chat-preview .chat-composer footer) {
  font-size: 9px;
}

.demo-content :deep(.postings-preview .page-heading p),
.demo-content :deep(.postings-preview .posting-list p),
.demo-content :deep(.postings-preview .posting-detail p) {
  font-size: 11px;
  line-height: 1.5;
}

.demo-content :deep(.postings-preview .posting-list strong),
.demo-content :deep(.postings-preview .posting-detail li strong) {
  font-size: 12px;
}

.demo-content :deep(.postings-preview small),
.demo-content :deep(.postings-preview .posting-list em) {
  font-size: 9px;
}

.demo-content :deep(.activity-preview .timeline strong),
.demo-content :deep(.activity-preview .ai-history strong) {
  font-size: 12px;
}

.demo-content :deep(.activity-preview .timeline p),
.demo-content :deep(.activity-preview .achievement p) {
  font-size: 10px;
  line-height: 1.55;
}

.demo-content :deep(.activity-preview small),
.demo-content :deep(.activity-preview .weekly li span),
.demo-content :deep(.activity-preview .weekly li b) {
  font-size: 9px;
}

.demo-content :deep(button) {
  min-height: 34px;
}

/* JOBI blue identity */
.roadmap-demo {
  --demo-ink: #10295d;
  background:
    linear-gradient(rgba(31, 91, 205, 0.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(31, 91, 205, 0.035) 1px, transparent 1px),
    radial-gradient(circle at 76% 0, rgba(38, 115, 255, 0.11), transparent 30%),
    #f5f9ff;
  background-size: 28px 28px, 28px 28px, auto, auto;
}

.demo-sidebar {
  border-color: #d4e2fb;
  background: rgba(255, 255, 255, 0.97);
}

.demo-brand {
  color: #0d2c6d;
}

.demo-brand > span {
  background: linear-gradient(145deg, #2c7cff, #1450ca);
  box-shadow: 0 5px 0 #0b3caa;
}

.sidebar-collapse-button {
  border-color: #ceddf7;
  color: #235fc8;
}

.sidebar-collapse-button:hover,
.demo-sidebar nav button:hover {
  color: #154eb8;
  background: #eef5ff;
}

.demo-sidebar nav button {
  color: #65789d;
}

.demo-sidebar nav button.active {
  color: #104dbd;
  background: #e9f2ff;
  box-shadow: inset 4px 0 #2874ef;
}

.demo-sidebar__profile,
.demo-bell {
  background: #edf4ff !important;
}

.demo-sidebar__profile > span,
.demo-avatar {
  background: #1b5bd5;
}

.demo-topbar {
  border-color: #d6e3f8;
}

.demo-streak {
  color: #714d00;
  background: #fff1b9;
}

.demo-hero {
  border-color: #bfd5fb;
  background:
    linear-gradient(rgba(27, 84, 190, 0.055) 1px, transparent 1px),
    linear-gradient(90deg, rgba(27, 84, 190, 0.055) 1px, transparent 1px),
    radial-gradient(circle at 90% 0, rgba(40, 116, 239, 0.2), transparent 34%),
    #fff;
  background-size: 24px 24px, 24px 24px, auto, auto;
  box-shadow: 0 18px 60px rgba(23, 72, 166, 0.11);
}

.demo-hero__kicker,
.demo-hero h1 {
  color: #0d347f;
}

.demo-goal-card {
  position: relative;
  overflow: visible;
  border-color: #c4d8fb;
  background: rgba(244, 249, 255, 0.92);
}

.demo-goal-mascot {
  position: absolute;
  top: -37px;
  right: -9px;
  width: 92px;
  filter: drop-shadow(0 10px 10px rgba(17, 67, 160, 0.18));
}

.demo-goal-card > span {
  color: #173466;
  background: #ffc928;
}

.demo-goal-card strong {
  color: #1458cf;
}

.demo-goal-card > div {
  background: #dce8fb;
}

.demo-goal-card > div i {
  background: linear-gradient(90deg, #1857d1, #49a7ff);
}

.demo-stats article {
  border-color: #d7e4f9;
  box-shadow: 0 8px 24px rgba(30, 79, 169, 0.05);
}

.demo-stats .blue,
.demo-stats .green {
  color: #1558cc;
  background: #e7f0ff;
}

.demo-stats .yellow {
  color: #7a5700;
  background: #fff2bd;
}

.demo-stats em {
  color: #1558cc;
}

.demo-content :deep(.home-welcome),
.demo-content :deep(.home-card),
.demo-content :deep(.chat-preview),
.demo-content :deep(.postings-preview > *),
.demo-content :deep(.activity-preview > *),
.demo-content :deep(.roadmap-path),
.demo-content :deep(.today-card),
.demo-content :deep(.heatmap-card) {
  border-color: #d2e1fa;
}

.demo-content :deep(.home-welcome) {
  background:
    linear-gradient(rgba(26, 82, 187, 0.05) 1px, transparent 1px),
    linear-gradient(90deg, rgba(26, 82, 187, 0.05) 1px, transparent 1px),
    radial-gradient(circle at 86% 12%, rgba(46, 124, 255, 0.2), transparent 34%),
    #fff;
  background-size: 24px 24px, 24px 24px, auto, auto;
}

.demo-content :deep(.home-welcome h1),
.demo-content :deep(.page-heading h1),
.demo-content :deep(.activity-preview h1) {
  color: #102f70;
}

.demo-content :deep(.home-welcome button),
.demo-content :deep(.ai-callout button),
.demo-content :deep(.next-action article > button),
.demo-content :deep(.chat-composer button.send),
.demo-content :deep(.chat-preview > aside header button) {
  border-bottom-color: #0b3fa9;
  background: #1b60db;
}

.demo-content :deep(.ai-callout),
.demo-content :deep(.analysis-card) {
  border-color: #bfd4fa;
  background: linear-gradient(135deg, #f8fbff, #eaf3ff);
}

.demo-content :deep(.ai-callout > span),
.demo-content :deep(.chat-room > header > span),
.demo-content :deep(.message-stream article > span) {
  background: #1b60db;
}

.demo-content :deep(.home-summary .mint),
.demo-content :deep(.home-summary .blue),
.demo-content :deep(.home-summary .purple) {
  color: #1558cc;
  background: #e7f0ff;
}

.demo-content :deep(.home-summary .yellow) {
  color: #785500;
  background: #fff2bd;
}

.demo-content :deep(.chat-preview > aside),
.demo-content :deep(.postings-preview),
.demo-content :deep(.activity-preview) {
  background-color: #f7faff;
}

.demo-content :deep(.chat-preview > aside > button.active),
.demo-content :deep(.chat-context) {
  border-color: #bfd4fa;
  color: #1558cc;
  background: #eef5ff;
}

.demo-content :deep(.message-stream article.user > span),
.demo-content :deep(.message-stream article.user p) {
  background: #1758cf;
}

.demo-content :deep(.section-kicker),
.demo-content :deep(.heatmap-card header span),
.demo-content :deep(.today-card header span),
.demo-content :deep(.page-heading span),
.demo-content :deep(.activity-heading span),
.demo-content :deep(.timeline header span),
.demo-content :deep(.weekly > span) {
  color: #1558cc;
}

.demo-content :deep(.roadmap-path) {
  background:
    radial-gradient(circle at 50% 20%, rgba(40, 116, 239, 0.11), transparent 30%),
    linear-gradient(180deg, #fff 0%, #f7faff 100%);
  box-shadow: 0 18px 60px rgba(26, 72, 158, 0.08);
}

.demo-content :deep(.roadmap-path h2),
.demo-content :deep(.today-card h3),
.demo-content :deep(.heatmap-card h3) {
  color: #102f70;
}

.demo-content :deep(.roadmap-node-row--complete .roadmap-node) {
  border-color: #a9c7fb;
}

.demo-content :deep(.roadmap-node-row--complete .roadmap-node__disc),
.demo-content :deep(.roadmap-connector--complete),
.demo-content :deep(.done .today-check) {
  border-color: #154bb6;
  background: #2367df;
}

.demo-content :deep(.roadmap-node-row--current .roadmap-node) {
  border-color: #54a1fa;
  background: linear-gradient(135deg, #fff, #edf5ff);
}

.demo-content :deep(.roadmap-node-row--current .roadmap-node__disc),
.demo-content :deep(.roadmap-node-row--current .roadmap-node__cta) {
  border-color: #0c48b7;
  background: #1d65df;
}

.demo-content :deep(.today-progress i) {
  background: linear-gradient(90deg, #1758cf, #49a7ff);
}

.demo-content :deep(.ai-replan) {
  border-color: #bfd4fa;
  background:
    radial-gradient(circle at 100% 0, rgba(36, 105, 225, 0.17), transparent 40%),
    linear-gradient(145deg, #f8fbff, #eaf3ff);
}

.demo-content :deep(.ai-replan header),
.demo-content :deep(.analysis-card header),
.demo-content :deep(.ai-history) {
  color: #1558cc;
}

.demo-content :deep(.ai-replan header > span),
.demo-content :deep(.ai-replan button) {
  border-bottom-color: #0b3fa9;
  background: #1b60db;
}

.demo-content :deep(.replan-flow > span) {
  border-color: #d3e1f8;
}

.demo-content :deep(.replan-flow > span.recommended) {
  border-color: #77a7f4;
}

.demo-content :deep(.heatmap i.level-1),
.demo-content :deep(.heatmap-legend i:nth-of-type(2)) {
  background: #cfe0ff;
}

.demo-content :deep(.heatmap i.level-2),
.demo-content :deep(.heatmap-legend i:nth-of-type(3)) {
  background: #8ab7ff;
}

.demo-content :deep(.heatmap i.level-3),
.demo-content :deep(.heatmap-legend i:nth-of-type(4)) {
  background: #4f8df0;
}

.demo-content :deep(.heatmap i.level-4),
.demo-content :deep(.heatmap-legend i:nth-of-type(5)) {
  background: #1755c8;
}

.demo-content :deep(.page-heading > button),
.demo-content :deep(.posting-detail footer button.primary),
.demo-content :deep(.fit-score > span),
.demo-content :deep(.posting-detail li > i.done) {
  border-bottom-color: #0b3fa9;
  background: #1b60db;
}

.demo-content :deep(.fit-score) {
  background: linear-gradient(135deg, #edf4ff, #fff9df);
}

.demo-content :deep(.fit-score strong),
.demo-content :deep(.posting-detail header small),
.demo-content :deep(.timeline header button) {
  color: #1558cc;
}

.demo-content :deep(.timeline article > i),
.demo-content :deep(.weekly li > i) {
  background: #286fe6;
}

.demo-content :deep(.timeline .green),
.demo-content :deep(.timeline .purple),
.demo-content :deep(.timeline .blue) {
  color: #1558cc;
  background: #e7f0ff;
}

.demo-content :deep(.ai-history) {
  border-color: #c8daf9;
  background: #eef5ff;
}

@media (max-width: 820px) {
  .demo-sidebar nav button.active {
    box-shadow: inset 0 3px #2874ef;
  }

  .demo-goal-mascot {
    width: 78px;
  }
}

/* Larger, more readable type scale */
.demo-sidebar nav button {
  font-size: 15px;
}

.demo-sidebar__profile strong {
  font-size: 14px;
}

.demo-sidebar__profile small {
  font-size: 11px;
}

.demo-topbar button {
  font-size: 13px;
}

.demo-topbar > button span {
  font-size: 11px;
}

.demo-streak {
  font-size: 12px;
}

.demo-hero > div > p {
  max-width: 660px;
  font-size: 15px;
  line-height: 1.65;
}

.demo-goal-card small,
.demo-goal-card em {
  font-size: 12px;
}

.demo-goal-card strong {
  font-size: 31px;
}

.demo-stats small {
  font-size: 12px;
}

.demo-stats strong {
  font-size: 18px;
}

.demo-stats em {
  font-size: 11px;
}

.demo-grid {
  grid-template-columns: minmax(0, 1fr) 360px;
}

.demo-content :deep(.home-welcome p) {
  font-size: 15px;
}

.demo-content :deep(.home-welcome button),
.demo-content :deep(.ai-callout button) {
  font-size: 13px;
}

.demo-content :deep(.home-summary small),
.demo-content :deep(.home-card header small),
.demo-content :deep(.recent-postings p) {
  font-size: 12px;
}

.demo-content :deep(.home-summary strong) {
  font-size: 19px;
}

.demo-content :deep(.home-summary em),
.demo-content :deep(.home-card header button),
.demo-content :deep(.score) {
  font-size: 11px;
}

.demo-content :deep(.home-card h2) {
  font-size: 19px;
}

.demo-content :deep(.home-card strong) {
  font-size: 14px;
}

.demo-content :deep(.home-card p) {
  font-size: 12px;
  line-height: 1.55;
}

.demo-content :deep(.next-action div span),
.demo-content :deep(.next-action article > button),
.demo-content :deep(.next-action article > em) {
  font-size: 11px;
}

.demo-content :deep(.ai-callout strong) {
  font-size: 17px;
}

.demo-content :deep(.ai-callout p) {
  font-size: 13px;
  line-height: 1.55;
}

.demo-content :deep(.chat-preview > aside strong) {
  font-size: 14px;
}

.demo-content :deep(.chat-preview > aside p) {
  font-size: 12px;
}

.demo-content :deep(.chat-preview > aside small),
.demo-content :deep(.chat-preview > aside header button) {
  font-size: 11px;
}

.demo-content :deep(.chat-room h1) {
  font-size: 17px;
}

.demo-content :deep(.chat-room > header em),
.demo-content :deep(.chat-context small) {
  font-size: 11px;
}

.demo-content :deep(.chat-context strong) {
  font-size: 13px;
}

.demo-content :deep(.message-stream article p) {
  font-size: 14px;
  line-height: 1.7;
}

.demo-content :deep(.analysis-card header strong) {
  font-size: 14px;
}

.demo-content :deep(.analysis-card small) {
  font-size: 11px;
}

.demo-content :deep(.analysis-card > div strong) {
  font-size: 12px;
}

.demo-content :deep(.chat-composer textarea) {
  font-size: 13px;
}

.demo-content :deep(.chat-composer footer) {
  font-size: 11px;
}

.demo-content :deep(.page-heading span),
.demo-content :deep(.activity-heading span) {
  font-size: 12px;
}

.demo-content :deep(.page-heading h1),
.demo-content :deep(.activity-heading h1) {
  font-size: 34px;
}

.demo-content :deep(.page-heading p),
.demo-content :deep(.activity-heading p) {
  font-size: 14px;
}

.demo-content :deep(.posting-toolbar input),
.demo-content :deep(.posting-toolbar button),
.demo-content :deep(.page-heading > button) {
  font-size: 12px;
}

.demo-content :deep(.posting-list strong),
.demo-content :deep(.posting-detail li strong) {
  font-size: 14px;
}

.demo-content :deep(.posting-list p),
.demo-content :deep(.posting-detail p) {
  font-size: 13px;
  line-height: 1.55;
}

.demo-content :deep(.postings-preview small),
.demo-content :deep(.posting-list em),
.demo-content :deep(.posting-detail footer button) {
  font-size: 11px;
}

.demo-content :deep(.posting-detail h2) {
  font-size: 22px;
}

.demo-content :deep(.posting-detail h3) {
  font-size: 15px;
}

.demo-content :deep(.fit-score strong) {
  font-size: 24px;
}

.demo-content :deep(.roadmap-path p) {
  font-size: 14px;
}

.demo-content :deep(.roadmap-path__legend),
.demo-content :deep(.roadmap-node__copy small),
.demo-content :deep(.roadmap-node__xp),
.demo-content :deep(.roadmap-node__cta) {
  font-size: 12px;
}

.demo-content :deep(.roadmap-node__copy strong) {
  font-size: 17px;
}

.demo-content :deep(.roadmap-node__copy span) {
  font-size: 13px;
}

.demo-content :deep(.today-card h3),
.demo-content :deep(.heatmap-card h3),
.demo-content :deep(.ai-replan h3) {
  font-size: 19px;
}

.demo-content :deep(.today-list strong),
.demo-content :deep(.replan-flow strong) {
  font-size: 13px;
}

.demo-content :deep(.today-list small),
.demo-content :deep(.today-list em),
.demo-content :deep(.today-card header span),
.demo-content :deep(.heatmap-card header span),
.demo-content :deep(.replan-flow small),
.demo-content :deep(.replan-flow em) {
  font-size: 11px;
}

.demo-content :deep(.ai-replan > p) {
  font-size: 13px;
}

.demo-content :deep(.ai-replan button),
.demo-content :deep(.applied-label),
.demo-content :deep(.heatmap-card footer) {
  font-size: 12px;
}

.demo-content :deep(.timeline h2),
.demo-content :deep(.weekly h2) {
  font-size: 19px;
}

.demo-content :deep(.timeline strong),
.demo-content :deep(.ai-history strong) {
  font-size: 14px;
}

.demo-content :deep(.timeline p),
.demo-content :deep(.achievement p) {
  font-size: 12px;
}

.demo-content :deep(.activity-preview small),
.demo-content :deep(.timeline header button),
.demo-content :deep(.weekly li span),
.demo-content :deep(.weekly li b) {
  font-size: 11px;
}

.demo-content :deep(.achievement h3) {
  font-size: 17px;
}

@media (max-width: 1080px) {
  .demo-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 820px) {
  .demo-sidebar nav button {
    font-size: 10px;
  }

  .demo-topbar button {
    font-size: 12px;
  }

  .demo-hero > div > p {
    font-size: 14px;
  }
}

/* Constellation roadmap experience */
.demo-content main.space-page {
  position: relative;
  padding: 30px;
  border-radius: 34px;
  background:
    radial-gradient(circle at 8% 5%, rgba(55, 126, 255, 0.2), transparent 28%),
    radial-gradient(circle at 92% 16%, rgba(33, 194, 255, 0.14), transparent 24%),
    linear-gradient(180deg, #071638, #030b22);
  box-shadow: 0 26px 80px rgba(3, 15, 49, 0.25);
}

.space-page .demo-hero {
  border-color: rgba(126, 176, 255, 0.34);
  background:
    linear-gradient(rgba(82, 145, 255, 0.07) 1px, transparent 1px),
    linear-gradient(90deg, rgba(82, 145, 255, 0.07) 1px, transparent 1px),
    radial-gradient(circle at 88% 8%, rgba(41, 122, 255, 0.28), transparent 34%),
    rgba(8, 27, 70, 0.88);
  background-size: 25px 25px, 25px 25px, auto, auto;
  box-shadow: inset 0 1px rgba(255, 255, 255, 0.1), 0 18px 50px rgba(0, 0, 0, 0.22);
}

.space-page .demo-hero__kicker {
  color: #76c8ff;
  filter: drop-shadow(0 0 8px rgba(90, 186, 255, 0.7));
}

.space-page .demo-hero h1 {
  color: #fff;
  text-shadow: 0 0 28px rgba(67, 142, 255, 0.38);
}

.space-page .demo-hero > div > p {
  color: #b8caec;
}

.space-page .demo-goal-card {
  border-color: rgba(124, 177, 255, 0.4);
  background: rgba(8, 30, 78, 0.78);
  box-shadow: inset 0 1px rgba(255, 255, 255, 0.1);
}

.space-page .demo-goal-card small,
.space-page .demo-goal-card em {
  color: #b5c8eb;
}

.space-page .demo-goal-card strong {
  color: #6ec9ff;
  text-shadow: 0 0 18px rgba(69, 174, 255, 0.45);
}

.space-page .demo-goal-card > div {
  background: rgba(159, 191, 240, 0.18);
}

.space-page .demo-stats article {
  border-color: rgba(124, 177, 255, 0.3);
  color: #eff6ff;
  background: rgba(11, 34, 82, 0.82);
  box-shadow: inset 0 1px rgba(255, 255, 255, 0.08);
}

.space-page .demo-stats small {
  color: #9fb5dc;
}

.space-page .demo-stats .blue,
.space-page .demo-stats .green {
  color: #7bcaff;
  background: rgba(49, 124, 241, 0.2);
}

.space-page .demo-stats .yellow {
  color: #ffd95a;
  background: rgba(255, 203, 44, 0.16);
}

.space-page .demo-stats em {
  color: #76c8ff;
}

.space-page :deep(.roadmap-path) {
  position: relative;
  overflow: hidden;
  border-color: rgba(119, 174, 255, 0.42);
  color: #eef6ff;
  background:
    linear-gradient(180deg, rgba(3, 12, 39, 0.22), rgba(3, 12, 39, 0.68)),
    url("/img/roadmap-space-bg.png") center top / cover no-repeat;
  box-shadow:
    inset 0 1px rgba(255, 255, 255, 0.12),
    0 24px 60px rgba(0, 0, 0, 0.28);
}

.space-page :deep(.roadmap-path::before) {
  position: absolute;
  top: 108px;
  right: 34px;
  color: rgba(255, 221, 95, 0.9);
  content: "✦";
  font-size: 27px;
  text-shadow:
    -520px 150px 0 rgba(110, 202, 255, 0.78),
    -395px 370px 0 rgba(255, 255, 255, 0.64),
    -70px 530px 0 rgba(110, 202, 255, 0.7);
  animation: star-twinkle 2.8s ease-in-out infinite;
}

.space-page :deep(.section-kicker) {
  color: #75c9ff;
}

.space-page :deep(.roadmap-path h2) {
  color: #fff;
}

.space-page :deep(.roadmap-path p) {
  color: #b7c9e9;
}

.space-page :deep(.roadmap-path__legend) {
  color: #c4d4ef;
  background: rgba(4, 17, 51, 0.66);
  box-shadow: inset 0 0 0 1px rgba(121, 176, 255, 0.18);
  backdrop-filter: blur(12px);
}

.space-page :deep(.roadmap-node) {
  border-color: rgba(113, 165, 244, 0.38);
  color: #eff6ff;
  background: rgba(5, 22, 62, 0.78);
  box-shadow:
    inset 0 1px rgba(255, 255, 255, 0.08),
    0 14px 35px rgba(0, 4, 22, 0.34);
  backdrop-filter: blur(14px);
}

.space-page :deep(.roadmap-node:hover) {
  border-color: rgba(126, 199, 255, 0.72);
  box-shadow:
    0 0 0 1px rgba(97, 183, 255, 0.18),
    0 0 30px rgba(45, 127, 255, 0.22),
    0 16px 38px rgba(0, 4, 22, 0.4);
}

.space-page :deep(.roadmap-node__disc) {
  position: relative;
  border-color: #376cbf;
  color: #9ccfff;
  background: radial-gradient(circle at 36% 30%, #356fda, #102a66 68%);
  box-shadow:
    0 0 0 7px rgba(65, 137, 255, 0.08),
    0 0 26px rgba(59, 145, 255, 0.34);
}

.space-page :deep(.roadmap-node__disc::after) {
  position: absolute;
  top: -12px;
  right: -9px;
  color: #fff;
  content: "✦";
  font-size: 14px;
  text-shadow: 0 0 12px #76c8ff;
}

.space-page :deep(.roadmap-node__copy small) {
  color: #78c7ff;
}

.space-page :deep(.roadmap-node__copy span) {
  color: #aabddd;
}

.space-page :deep(.roadmap-node__xp),
.space-page :deep(.roadmap-node__cta) {
  color: #c6ddff;
  background: rgba(64, 128, 224, 0.18);
}

.space-page :deep(.roadmap-node-row--complete .roadmap-node) {
  border-color: rgba(89, 181, 255, 0.62);
}

.space-page :deep(.roadmap-node-row--complete .roadmap-node__disc) {
  border-color: #4798ee;
  background: radial-gradient(circle at 35% 30%, #5fbcff, #1760cf 68%);
}

.space-page :deep(.roadmap-node-row--current .roadmap-node) {
  border-color: #ffd354;
  background: linear-gradient(135deg, rgba(17, 46, 99, 0.94), rgba(42, 77, 139, 0.84));
  box-shadow:
    0 0 0 1px rgba(255, 211, 84, 0.2),
    0 0 34px rgba(255, 196, 47, 0.19),
    0 18px 42px rgba(0, 4, 22, 0.42);
}

.space-page :deep(.roadmap-node-row--current .roadmap-node__disc) {
  border-color: #e0a916;
  color: #173466;
  background: radial-gradient(circle at 35% 25%, #fff8b5, #ffd339 58%, #ef9e14);
  box-shadow:
    0 0 0 8px rgba(255, 210, 56, 0.1),
    0 0 32px rgba(255, 208, 54, 0.52);
}

.space-page :deep(.roadmap-node-row--current .roadmap-node__cta) {
  color: #173466;
  background: #ffd33d;
}

.space-page :deep(.roadmap-node-row--available .roadmap-node) {
  border-color: rgba(114, 197, 255, 0.62);
}

.space-page :deep(.roadmap-node-row--available .roadmap-node__disc) {
  border-color: #57a9f5;
  color: #fff;
  background: radial-gradient(circle at 35% 30%, #5fc8ff, #1452bc 70%);
}

.space-page :deep(.roadmap-node-row--locked .roadmap-node) {
  border-color: rgba(105, 132, 181, 0.25);
  color: #91a3c3;
  background: rgba(7, 21, 54, 0.68);
}

.space-page :deep(.roadmap-connector) {
  width: 4px;
  height: 42px;
  background: repeating-linear-gradient(
    to bottom,
    rgba(121, 184, 255, 0.8) 0,
    rgba(121, 184, 255, 0.8) 5px,
    transparent 5px,
    transparent 11px
  );
  filter: drop-shadow(0 0 6px rgba(68, 155, 255, 0.9));
}

.space-page :deep(.roadmap-connector--complete) {
  background: linear-gradient(#70caff, #428cff);
  box-shadow: 0 0 12px rgba(73, 158, 255, 0.72);
}

.space-page :deep(.today-card),
.space-page :deep(.heatmap-card),
.space-page :deep(.ai-replan) {
  border-color: rgba(116, 171, 255, 0.34);
  color: #edf5ff;
  background:
    radial-gradient(circle at 100% 0, rgba(50, 126, 249, 0.15), transparent 38%),
    rgba(8, 28, 70, 0.88);
  box-shadow: inset 0 1px rgba(255, 255, 255, 0.08);
  backdrop-filter: blur(14px);
}

.space-page :deep(.today-card h3),
.space-page :deep(.heatmap-card h3),
.space-page :deep(.ai-replan h3),
.space-page :deep(.today-list strong),
.space-page :deep(.replan-flow strong) {
  color: #f2f7ff;
}

.space-page :deep(.today-list button),
.space-page :deep(.replan-flow > span) {
  border-color: rgba(110, 164, 244, 0.25);
  color: #eaf3ff;
  background: rgba(5, 19, 52, 0.5);
}

.space-page :deep(.today-list small),
.space-page :deep(.ai-replan > p),
.space-page :deep(.replan-flow em),
.space-page :deep(.heatmap-card footer) {
  color: #a8bade;
}

.space-page :deep(.heatmap i) {
  background: rgba(117, 148, 201, 0.16);
}

@keyframes star-twinkle {
  0%,
  100% {
    opacity: 0.45;
    transform: scale(0.88);
  }
  50% {
    opacity: 1;
    transform: scale(1.08);
  }
}

@media (max-width: 820px) {
  .demo-content main.space-page {
    padding: 14px;
    border-radius: 22px;
  }

  .space-page :deep(.roadmap-path::before) {
    display: none;
  }
}
</style>
