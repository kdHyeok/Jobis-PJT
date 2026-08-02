<script setup lang="ts">
import {
  Check,
  LockKeyhole,
  Sparkles,
} from "@lucide/vue";

import type { RoadmapNode } from "@/demo/roadmap-demo";

defineProps<{
  nodes: RoadmapNode[];
  selectedId: string;
}>();

defineEmits<{
  select: [node: RoadmapNode];
}>();

const nodeArtwork: Record<string, string> = {
  goal: "/img/roadmap-nodes/goal-star.png",
  gap: "/img/roadmap-nodes/analytics-moon.png",
  sql: "/img/roadmap-nodes/sql-planet.png",
  project: "/img/roadmap-nodes/api-planet.png",
  portfolio: "/img/roadmap-nodes/portfolio-comet.png",
  essay: "/img/roadmap-nodes/document-star.png",
  interview: "/img/roadmap-nodes/constellation.png",
  apply: "/img/roadmap-nodes/success-sun.png",
};

function artworkFor(node: RoadmapNode) {
  return nodeArtwork[node.id] ?? nodeArtwork.goal;
}
</script>

<template>
  <section class="roadmap-path" aria-label="취업 준비 로드맵">
    <header class="roadmap-path__heading">
      <div>
        <span class="section-kicker" aria-label="개인 로드맵"><Sparkles :size="21" /></span>
        <h2>합격까지 이어지는 나의 경로</h2>
        <p>현재 단계부터 하나씩 완료하면 다음 준비가 열려요.</p>
      </div>
      <span class="roadmap-path__legend">
        <i class="done" /> 완료
        <i class="now" /> 진행 중
        <i /> 잠김
      </span>
    </header>

    <div class="roadmap-path__track">
      <template v-for="(node, index) in nodes" :key="node.id">
        <article
          class="roadmap-node-row"
          :class="[
            `roadmap-node-row--${node.state}`,
            index % 2 ? 'roadmap-node-row--right' : 'roadmap-node-row--left',
          ]"
        >
          <button
            class="roadmap-node"
            :class="{ 'roadmap-node--selected': selectedId === node.id }"
            type="button"
            :aria-label="`${node.title} 상세 보기`"
            @click="$emit('select', node)"
          >
            <span class="roadmap-node__disc">
              <img :src="artworkFor(node)" alt="" />
              <span v-if="node.state === 'complete'" class="roadmap-node__state-badge complete">
                <Check :size="15" :stroke-width="3.2" />
              </span>
              <span v-else-if="node.state === 'locked'" class="roadmap-node__state-badge locked">
                <LockKeyhole :size="13" :stroke-width="2.8" />
              </span>
            </span>
            <span class="roadmap-node__copy">
              <small>{{ node.duration }}</small>
              <strong>{{ node.title }}</strong>
              <span>{{ node.subtitle }}</span>
            </span>
            <span v-if="node.state === 'current'" class="roadmap-node__cta">
              계속하기
            </span>
            <span v-else-if="node.state !== 'locked'" class="roadmap-node__xp">
              +{{ node.xp }} XP
            </span>
          </button>
        </article>
        <span
          v-if="index < nodes.length - 1"
          class="roadmap-connector"
          :class="{ 'roadmap-connector--complete': node.state === 'complete' }"
          aria-hidden="true"
        />
      </template>
    </div>
  </section>
</template>

<style scoped>
.roadmap-path {
  padding: 28px 28px 42px;
  border: 1px solid #dce7e3;
  border-radius: 28px;
  background:
    radial-gradient(circle at 50% 20%, rgba(87, 193, 255, 0.1), transparent 28%),
    linear-gradient(180deg, #fff 0%, #fbfefc 100%);
  box-shadow: 0 18px 60px rgba(55, 91, 78, 0.08);
}

.roadmap-path__heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
}

.section-kicker {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #348d69;
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.12em;
}

.roadmap-path h2 {
  margin: 8px 0 5px;
  color: #243b34;
  font-size: clamp(22px, 2.4vw, 30px);
  letter-spacing: -0.05em;
}

.roadmap-path p {
  margin: 0;
  color: #7b8d86;
  font-size: 13px;
}

.roadmap-path__legend {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 12px;
  border-radius: 12px;
  color: #809089;
  background: #f5f8f6;
  font-size: 10px;
  font-weight: 800;
  white-space: nowrap;
}

.roadmap-path__legend i {
  width: 7px;
  height: 7px;
  margin-left: 6px;
  border-radius: 50%;
  background: #cbd4d0;
}

.roadmap-path__legend i:first-child {
  margin-left: 0;
}

.roadmap-path__legend i.done {
  background: #58cc78;
}

.roadmap-path__legend i.now {
  background: #1cb0f6;
}

.roadmap-path__track {
  position: relative;
  display: flex;
  width: min(100%, 610px);
  align-items: center;
  flex-direction: column;
  margin: 38px auto 0;
}

.roadmap-node-row {
  display: flex;
  width: 100%;
}

.roadmap-node-row--left {
  justify-content: flex-start;
  padding-right: 90px;
}

.roadmap-node-row--right {
  justify-content: flex-end;
  padding-left: 90px;
}

.roadmap-node {
  display: grid;
  width: min(100%, 420px);
  min-height: 96px;
  grid-template-columns: 72px minmax(0, 1fr) auto;
  align-items: center;
  gap: 14px;
  padding: 12px 15px 16px 12px;
  border: 2px solid #e2e9e6;
  border-bottom-width: 6px;
  border-radius: 24px;
  color: #2c4039;
  background: #fff;
  cursor: pointer;
  text-align: left;
  transition: transform 140ms ease, border-color 140ms ease, box-shadow 140ms ease;
}

.roadmap-node:hover {
  transform: translateY(-2px);
  box-shadow: 0 12px 28px rgba(51, 83, 72, 0.1);
}

.roadmap-node:active {
  transform: translateY(3px);
  border-bottom-width: 3px;
}

.roadmap-node--selected {
  outline: 3px solid rgba(28, 176, 246, 0.16);
  outline-offset: 3px;
}

.roadmap-node__disc {
  display: grid;
  width: 66px;
  height: 66px;
  place-items: center;
  border: 3px solid #dce5e1;
  border-bottom-width: 7px;
  border-radius: 50%;
  color: #82918b;
  background: #f4f7f5;
}

.roadmap-node__copy {
  display: grid;
  min-width: 0;
  gap: 3px;
}

.roadmap-node__copy small {
  color: #879891;
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.07em;
  text-transform: uppercase;
}

.roadmap-node__copy strong {
  overflow: hidden;
  font-size: 16px;
  letter-spacing: -0.02em;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.roadmap-node__copy span {
  overflow: hidden;
  color: #84928d;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.roadmap-node__xp,
.roadmap-node__cta {
  align-self: center;
  padding: 7px 9px;
  border-radius: 9px;
  color: #608073;
  background: #edf4f0;
  font-size: 11px;
  font-weight: 900;
  white-space: nowrap;
}

.roadmap-node-row--complete .roadmap-node {
  border-color: #a8e5b7;
}

.roadmap-node-row--complete .roadmap-node__disc {
  border-color: #39ad5a;
  color: #fff;
  background: #58cc78;
}

.roadmap-node-row--current .roadmap-node {
  border-color: #73cef6;
  background: linear-gradient(135deg, #fff, #effaff);
  box-shadow: 0 14px 34px rgba(28, 176, 246, 0.14);
}

.roadmap-node-row--current .roadmap-node__disc {
  border-color: #138fcb;
  color: #fff;
  background: #1cb0f6;
  animation: current-pulse 2s ease-in-out infinite;
}

.roadmap-node-row--current .roadmap-node__cta {
  color: #fff;
  background: #1cb0f6;
}

.roadmap-node-row--available .roadmap-node {
  border-color: #ffd96a;
}

.roadmap-node-row--available .roadmap-node__disc {
  border-color: #e3ab12;
  color: #765700;
  background: #ffd84d;
}

.roadmap-node-row--locked .roadmap-node {
  border-color: #e6ebe8;
  color: #94a09b;
  background: #f7f9f8;
  box-shadow: none;
}

.roadmap-connector {
  width: 7px;
  height: 31px;
  margin: 3px 0;
  border-radius: 99px;
  background: repeating-linear-gradient(
    to bottom,
    #d7dfdb 0,
    #d7dfdb 7px,
    transparent 7px,
    transparent 12px
  );
}

.roadmap-connector--complete {
  background: #8bdd9e;
}

@keyframes current-pulse {
  0%,
  100% {
    box-shadow: 0 7px 0 #138fcb, 0 0 0 0 rgba(28, 176, 246, 0.26);
  }
  50% {
    box-shadow: 0 7px 0 #138fcb, 0 0 0 12px rgba(28, 176, 246, 0);
  }
}

@media (max-width: 680px) {
  .roadmap-path {
    padding: 22px 16px 34px;
  }

  .roadmap-path__heading {
    flex-direction: column;
  }

  .roadmap-path__legend {
    display: none;
  }

  .roadmap-node-row--left,
  .roadmap-node-row--right {
    padding: 0;
  }

  .roadmap-node {
    grid-template-columns: 58px minmax(0, 1fr);
  }

  .roadmap-node__disc {
    width: 54px;
    height: 54px;
  }

  .roadmap-node__xp,
  .roadmap-node__cta {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .roadmap-node-row--current .roadmap-node__disc {
    animation: none;
  }
}

/* Illustrated constellation nodes */
.roadmap-path__track {
  width: min(100%, 720px);
  margin-top: 46px;
}

.roadmap-node-row--left {
  padding-right: 110px;
}

.roadmap-node-row--right {
  padding-left: 110px;
}

.roadmap-node {
  width: min(100%, 500px);
  min-height: 126px;
  grid-template-columns: 108px minmax(0, 1fr) auto;
  gap: 16px;
  padding: 10px 18px 12px 10px;
}

.roadmap-node__disc,
.roadmap-node-row--complete .roadmap-node__disc,
.roadmap-node-row--current .roadmap-node__disc,
.roadmap-node-row--available .roadmap-node__disc {
  position: relative;
  width: 104px;
  height: 104px;
  border: 0 !important;
  background: transparent !important;
  box-shadow: none !important;
}

.roadmap-node__disc::after {
  display: none;
}

.roadmap-node__disc img {
  width: 104px;
  height: 104px;
  object-fit: contain;
  filter: drop-shadow(0 10px 15px rgba(39, 113, 255, 0.32));
  transition: transform 180ms ease, filter 180ms ease;
}

.roadmap-node:hover .roadmap-node__disc img {
  transform: translateY(-3px) scale(1.06) rotate(-2deg);
  filter: drop-shadow(0 14px 20px rgba(65, 157, 255, 0.52));
}

.roadmap-node-row--current .roadmap-node__disc {
  animation: illustrated-node-pulse 2.2s ease-in-out infinite;
}

.roadmap-node-row--current .roadmap-node__disc img {
  filter: drop-shadow(0 0 22px rgba(255, 211, 61, 0.7));
}

.roadmap-node-row--locked .roadmap-node__disc img {
  opacity: 0.58;
  filter: grayscale(0.72) saturate(0.55) drop-shadow(0 8px 12px rgba(26, 56, 116, 0.22));
}

.roadmap-node__state-badge {
  position: absolute;
  right: 2px;
  bottom: 4px;
  display: grid;
  width: 27px;
  height: 27px;
  place-items: center;
  border: 3px solid #fff;
  border-radius: 50%;
  color: #fff;
  box-shadow: 0 5px 12px rgba(3, 17, 55, 0.25);
}

.roadmap-node__state-badge.complete {
  background: #1c67dc;
}

.roadmap-node__state-badge.locked {
  color: #5d7098;
  background: #e8effb;
}

.roadmap-connector {
  position: relative;
  width: 4px;
  height: 54px;
  margin: 2px 0;
}

.roadmap-connector::before,
.roadmap-connector::after {
  position: absolute;
  left: 50%;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #80caff;
  box-shadow: 0 0 12px rgba(87, 178, 255, 0.95);
  content: "";
  transform: translateX(-50%);
}

.roadmap-connector::before {
  top: 7px;
}

.roadmap-connector::after {
  bottom: 7px;
}

@keyframes illustrated-node-pulse {
  0%,
  100% {
    transform: scale(1);
  }
  50% {
    transform: scale(1.045);
  }
}

@media (max-width: 680px) {
  .roadmap-node-row--left,
  .roadmap-node-row--right {
    padding: 0;
  }

  .roadmap-node {
    min-height: 104px;
    grid-template-columns: 84px minmax(0, 1fr);
  }

  .roadmap-node__disc,
  .roadmap-node-row--complete .roadmap-node__disc,
  .roadmap-node-row--current .roadmap-node__disc,
  .roadmap-node-row--available .roadmap-node__disc,
  .roadmap-node__disc img {
    width: 82px;
    height: 82px;
  }
}
</style>
