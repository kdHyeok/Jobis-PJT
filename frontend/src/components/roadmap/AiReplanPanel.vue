<script setup lang="ts">
import { ArrowRight, BrainCircuit, Check, RotateCw, Sparkles } from "@lucide/vue";

defineProps<{
  applied: boolean;
}>();

defineEmits<{
  apply: [];
}>();
</script>

<template>
  <section class="ai-replan" :class="{ applied }">
    <header>
      <span><BrainCircuit :size="20" /></span>
      <div>
        <h3>{{ applied ? "새 경로가 적용됐어요" : "더 빠른 경로를 찾았어요" }}</h3>
      </div>
      <Sparkles :size="18" />
    </header>

    <p v-if="!applied">
      최근 프로젝트 경험을 반영하면 자격증 준비보다 작은 금융 API 프로젝트를 먼저
      완성하는 편이 적합도를 더 크게 높일 수 있어요.
    </p>
    <p v-else>
      로드맵과 오늘 할 일을 새 경로에 맞게 조정했습니다. 언제든 이전 경로로 되돌릴 수
      있어요.
    </p>

    <div class="replan-flow">
      <span>
        <small>기존</small>
        <strong>자격증 준비</strong>
        <em>+3점 · 14일</em>
      </span>
      <ArrowRight :size="18" />
      <span class="recommended">
        <small>추천</small>
        <strong>금융 API 프로젝트</strong>
        <em>+8점 · 10일</em>
      </span>
    </div>

    <button v-if="!applied" type="button" @click="$emit('apply')">
      <RotateCw :size="15" /> 추천 경로 적용하기
    </button>
    <span v-else class="applied-label"><Check :size="14" /> 로드맵 반영 완료</span>
  </section>
</template>

<style scoped>
.ai-replan {
  padding: 20px;
  border: 1px solid #d5c9fa;
  border-radius: 22px;
  background:
    radial-gradient(circle at 100% 0, rgba(124, 92, 226, 0.16), transparent 38%),
    linear-gradient(145deg, #fbf9ff, #f6f2ff);
}

.ai-replan header {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  color: #7554d5;
}

.ai-replan header > span {
  display: grid;
  width: 39px;
  height: 39px;
  place-items: center;
  border-radius: 13px;
  color: #fff;
  background: #8464e8;
}

.ai-replan header small {
  color: #8066ca;
  font-size: 8px;
  font-weight: 900;
  letter-spacing: 0.09em;
}

.ai-replan h3 {
  margin: 3px 0 0;
  color: #3e315f;
  font-size: 18px;
}

.ai-replan > p {
  margin: 14px 0;
  color: #6d6384;
  font-size: 12px;
  line-height: 1.65;
}

.replan-flow {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  gap: 7px;
}

.replan-flow > span {
  display: grid;
  gap: 3px;
  padding: 11px;
  border: 1px solid #e4ddf4;
  border-radius: 13px;
  background: rgba(255, 255, 255, 0.76);
}

.replan-flow > span.recommended {
  border-color: #a994ed;
  background: #fff;
}

.replan-flow small {
  color: #9b91ad;
  font-size: 9px;
  font-weight: 900;
}

.replan-flow strong {
  color: #4e4465;
  font-size: 11px;
}

.replan-flow em {
  color: #8879a8;
  font-size: 9px;
  font-style: normal;
}

.ai-replan button,
.applied-label {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin-top: 13px;
  padding: 10px;
  border: 0;
  border-bottom: 4px solid #5e42bb;
  border-radius: 12px;
  color: #fff;
  background: #8464e8;
  cursor: pointer;
  font-size: 11px;
  font-weight: 900;
}

.ai-replan button:active {
  transform: translateY(2px);
  border-bottom-width: 2px;
}

.ai-replan.applied {
  border-color: #b9dfc4;
  background: #f4fbf6;
}

.applied-label {
  border: 0;
  color: #2b8a4b;
  background: #def3e4;
}
</style>
