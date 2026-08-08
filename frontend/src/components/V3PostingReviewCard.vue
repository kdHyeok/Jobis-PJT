<script setup lang="ts">
import {
  BriefcaseBusiness,
  Check,
  ChevronDown,
  FileText,
  PencilLine,
  Sparkles,
  X,
} from "@lucide/vue";
import { computed } from "vue";

import type { V3PostingReview } from "@/types";

const props = withDefaults(defineProps<{
  review: V3PostingReview;
  busy?: boolean;
  allowRevision?: boolean;
  confirmed?: boolean;
}>(), {
  busy: false,
  allowRevision: false,
  confirmed: false,
});

const emit = defineEmits<{
  confirm: [];
  revise: [];
  cancel: [];
}>();

const experienceLabel = computed(() => {
  const experience = props.review.experience;
  if (props.review.selectedExperienceTrack === "NEW_GRADUATE") return "신입 기준";
  const months = experience.minMonths ?? experience.experiencedMinMonths;
  if (props.review.selectedExperienceTrack === "EXPERIENCED" && months) {
    return months % 12 === 0
      ? `경력 ${months / 12}년 이상 기준`
      : `경력 ${months}개월 이상 기준`;
  }
  if (experience.kind === "NO_RESTRICTION") return "경력 무관";
  return "경력 조건 확인됨";
});
</script>

<template>
  <section class="posting-review-card">
    <header class="posting-review-card__header">
      <span><Sparkles :size="21" /></span>
      <div>
        <small>{{ confirmed ? "확인한 분석 범위" : "선택 범위 최종 확인" }}</small>
        <h3>
          {{
            confirmed
              ? "이 공고 내용으로 프로젝트와 로드맵 분석을 진행했어요"
              : "프로젝트를 만들기 전에 공고 내용을 확인해 주세요"
          }}
        </h3>
        <p>
          {{
            confirmed
              ? "당시 선택한 직무와 경력 조건을 그대로 보관하고 있습니다."
              : "선택한 직무와 경력 조건에 해당하는 내용만 정리했습니다."
          }}
        </p>
      </div>
    </header>

    <div class="posting-review-card__identity">
      <span><BriefcaseBusiness :size="20" /></span>
      <div>
        <small>{{ review.companyName ?? "회사명 확인 필요" }}</small>
        <strong>{{ review.positionTitle }}</strong>
        <p v-if="review.postingTitle && review.postingTitle !== review.positionTitle">
          {{ review.postingTitle }}
        </p>
      </div>
    </div>

    <div class="posting-review-card__chips">
      <span>{{ review.positionTitle }}</span>
      <span>{{ experienceLabel }}</span>
    </div>

    <section
      v-if="review.responsibilities.length || review.responsibilityRequirements.length"
      class="posting-review-card__section"
    >
      <h4>주요 업무</h4>
      <ul>
        <li v-for="item in review.responsibilities" :key="item.responsibilityId">
          {{ item.atomicText || item.sourceText }}
        </li>
        <li
          v-for="item in review.responsibilityRequirements"
          :key="item.requirementId"
        >
          {{ item.atomicText || item.sourceText }}
        </li>
      </ul>
    </section>

    <section v-if="review.requiredRequirements.length" class="posting-review-card__section">
      <h4><span class="requirement-dot requirement-dot--required" />필수 요건</h4>
      <ul>
        <li v-for="item in review.requiredRequirements" :key="item.requirementId">
          {{ item.atomicText || item.sourceText }}
        </li>
      </ul>
    </section>

    <section v-if="review.preferredRequirements.length" class="posting-review-card__section">
      <h4><span class="requirement-dot requirement-dot--preferred" />우대 요건</h4>
      <ul>
        <li v-for="item in review.preferredRequirements" :key="item.requirementId">
          {{ item.atomicText || item.sourceText }}
        </li>
      </ul>
    </section>

    <details class="posting-review-card__original">
      <summary>
        <span><FileText :size="16" /> 전체 원문 보기</span>
        <ChevronDown :size="16" />
      </summary>
      <pre>{{ review.originalText }}</pre>
    </details>

    <div v-if="confirmed" class="posting-review-card__confirmed">
      <Check :size="17" /> 이 내용으로 계속하기를 선택했습니다
    </div>

    <div v-else class="posting-review-card__actions">
      <button
        v-if="allowRevision"
        class="press-button press-button--ghost"
        type="button"
        :disabled="busy"
        @click="emit('revise')"
      >
        <PencilLine :size="17" /> 원문 수정·다시 분석
      </button>
      <button
        class="press-button press-button--ghost"
        type="button"
        :disabled="busy"
        @click="emit('cancel')"
      >
        <X :size="17" /> 분석 취소
      </button>
      <button
        class="press-button press-button--primary"
        type="button"
        :disabled="busy"
        @click="emit('confirm')"
      >
        <Check :size="18" /> 이 내용으로 프로젝트·로드맵 만들기
      </button>
    </div>
  </section>
</template>

<style scoped>
.posting-review-card {
  display: grid;
  gap: 16px;
  width: 100%;
  padding: 18px;
  border: 2px solid #dbeafe;
  border-bottom-width: 5px;
  border-radius: 20px;
  background: #fff;
  color: #172554;
}

.posting-review-card__header,
.posting-review-card__identity {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.posting-review-card__header > span,
.posting-review-card__identity > span {
  display: grid;
  flex: 0 0 42px;
  width: 42px;
  height: 42px;
  place-items: center;
  border-radius: 14px;
  background: #dbeafe;
  color: #2563eb;
}

.posting-review-card small {
  color: #64748b;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: .04em;
}

.posting-review-card h3,
.posting-review-card h4,
.posting-review-card p {
  margin: 0;
}

.posting-review-card h3 {
  margin-top: 3px;
  font-size: 18px;
  line-height: 1.35;
}

.posting-review-card__header p,
.posting-review-card__identity p {
  margin-top: 5px;
  color: #64748b;
  line-height: 1.5;
}

.posting-review-card__identity {
  padding: 14px;
  border-radius: 16px;
  background: #f8fafc;
}

.posting-review-card__identity strong {
  display: block;
  margin-top: 2px;
  font-size: 17px;
}

.posting-review-card__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.posting-review-card__chips span {
  padding: 7px 11px;
  border: 1px solid #bfdbfe;
  border-radius: 999px;
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 13px;
  font-weight: 800;
}

.posting-review-card__confirmed {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 11px 13px;
  border-radius: 13px;
  color: #166534;
  background: #dcfce7;
  font-size: 13px;
  font-weight: 850;
}

.posting-review-card__section {
  display: grid;
  gap: 8px;
}

.posting-review-card__section h4 {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 15px;
}

.posting-review-card__section ul {
  display: grid;
  gap: 7px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.posting-review-card__section li {
  position: relative;
  padding-left: 15px;
  color: #334155;
  line-height: 1.55;
}

.posting-review-card__section li::before {
  position: absolute;
  top: .7em;
  left: 2px;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #60a5fa;
  content: "";
}

.requirement-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
}

.requirement-dot--required { background: #ef4444; }
.requirement-dot--preferred { background: #f59e0b; }

.posting-review-card__original {
  overflow: hidden;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  background: #f8fafc;
}

.posting-review-card__original summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  cursor: pointer;
  font-weight: 800;
  list-style: none;
}

.posting-review-card__original summary span {
  display: flex;
  align-items: center;
  gap: 7px;
}

.posting-review-card__original pre {
  max-height: 320px;
  margin: 0;
  padding: 14px;
  overflow: auto;
  border-top: 1px solid #e2e8f0;
  color: #475569;
  font: inherit;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
}

.posting-review-card__actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 9px;
}

@media (max-width: 680px) {
  .posting-review-card__actions button { width: 100%; }
}
</style>
