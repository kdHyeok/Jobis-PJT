<script setup lang="ts">
import { Check, Clock3, LockKeyhole, Sparkles, X, Zap } from "@lucide/vue";

import type { RoadmapNode } from "@/demo/roadmap-demo";

defineProps<{
  node: RoadmapNode | null;
}>();

defineEmits<{
  close: [];
}>();
</script>

<template>
  <Transition name="drawer">
    <aside v-if="node" class="node-drawer" aria-label="로드맵 단계 상세">
      <button class="drawer-close" type="button" aria-label="닫기" @click="$emit('close')">
        <X :size="18" />
      </button>

      <span class="drawer-kicker"><Sparkles :size="13" /> QUEST DETAIL</span>
      <h2>{{ node.title }}</h2>
      <p>{{ node.description }}</p>

      <div class="drawer-meta">
        <span><Clock3 :size="14" /> {{ node.duration }}</span>
        <span><Zap :size="14" /> +{{ node.xp }} XP</span>
      </div>

      <section>
        <h3>완료 조건</h3>
        <ul>
          <li v-for="item in node.checklist" :key="item">
            <Check :size="14" /> {{ item }}
          </li>
        </ul>
      </section>

      <div v-if="node.unlockHint" class="unlock-hint">
        <LockKeyhole :size="15" />
        <span>
          <strong>해제 조건</strong>
          {{ node.unlockHint }}
        </span>
      </div>

      <button v-if="node.state === 'current'" class="drawer-primary" type="button">
        이어서 준비하기
      </button>
      <button v-else-if="node.state === 'available'" class="drawer-secondary" type="button">
        이 단계 먼저 시작하기
      </button>
    </aside>
  </Transition>
</template>

<style scoped>
.node-drawer {
  position: fixed;
  z-index: 60;
  top: 18px;
  right: 18px;
  bottom: 18px;
  width: min(390px, calc(100vw - 36px));
  overflow: auto;
  padding: 28px;
  border: 1px solid #d9e4df;
  border-radius: 26px;
  background: rgba(255, 255, 255, 0.97);
  box-shadow: 0 30px 90px rgba(31, 55, 46, 0.24);
  backdrop-filter: blur(18px);
}

.drawer-close {
  position: absolute;
  top: 17px;
  right: 17px;
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  border: 0;
  border-radius: 11px;
  color: #6e7e77;
  background: #eff4f1;
  cursor: pointer;
}

.drawer-kicker {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: #248b65;
  font-size: 9px;
  font-weight: 900;
  letter-spacing: 0.12em;
}

.node-drawer h2 {
  margin: 12px 0 8px;
  color: #273c35;
  font-size: 25px;
  letter-spacing: -0.05em;
}

.node-drawer > p {
  margin: 0;
  color: #75867f;
  font-size: 13px;
  line-height: 1.7;
}

.drawer-meta {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin: 20px 0;
}

.drawer-meta span {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 11px;
  border-radius: 12px;
  color: #567066;
  background: #f1f6f3;
  font-size: 11px;
  font-weight: 850;
}

.node-drawer section {
  padding: 17px;
  border: 1px solid #e1e8e4;
  border-radius: 17px;
  background: #fbfdfc;
}

.node-drawer h3 {
  margin: 0 0 12px;
  color: #33473f;
  font-size: 14px;
}

.node-drawer ul {
  display: grid;
  gap: 9px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.node-drawer li {
  display: flex;
  align-items: center;
  gap: 7px;
  color: #667a71;
  font-size: 12px;
}

.node-drawer li svg {
  color: #4eb76b;
}

.unlock-hint {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  margin-top: 12px;
  padding: 14px;
  border-radius: 14px;
  color: #786a46;
  background: #fff7df;
  font-size: 11px;
  line-height: 1.5;
}

.unlock-hint strong {
  display: block;
  margin-bottom: 2px;
  color: #6a5621;
}

.drawer-primary,
.drawer-secondary {
  width: 100%;
  margin-top: 18px;
  padding: 13px;
  border: 0;
  border-bottom: 5px solid #0e8fc9;
  border-radius: 14px;
  color: #fff;
  background: #1cb0f6;
  cursor: pointer;
  font-size: 13px;
  font-weight: 900;
}

.drawer-secondary {
  border-bottom-color: #d5a718;
  color: #5c480c;
  background: #ffd84d;
}

.drawer-enter-active,
.drawer-leave-active {
  transition: transform 200ms ease, opacity 200ms ease;
}

.drawer-enter-from,
.drawer-leave-to {
  opacity: 0;
  transform: translateX(30px);
}
</style>
