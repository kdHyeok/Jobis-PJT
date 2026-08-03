<script setup lang="ts">
import {
  Check,
  CirclePause,
  GitMerge,
  LoaderCircle,
  RefreshCw,
  Split,
  UserRoundCheck,
  X,
} from "@lucide/vue";
import { onMounted, ref } from "vue";

import { api } from "@/api";
import type {
  AssessmentReviewItem,
  PostingDuplicateCandidate,
} from "@/types";

const tab = ref<"POSTINGS" | "ASSESSMENTS">("POSTINGS");
const duplicates = ref<PostingDuplicateCandidate[]>([]);
const reviews = ref<AssessmentReviewItem[]>([]);
const loading = ref(true);
const actionId = ref<string | null>(null);
const error = ref("");

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [postingItems, reviewItems] = await Promise.all([
      api.operatorPostingDuplicates(),
      api.operatorAssessmentReviews(),
    ]);
    duplicates.value = postingItems;
    reviews.value = reviewItems;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "운영 검토함을 불러오지 못했습니다.";
  } finally {
    loading.value = false;
  }
}

async function resolveDuplicate(
  item: PostingDuplicateCandidate,
  action: "MERGE" | "SEPARATE" | "HOLD",
  canonicalPostingId: string | null = null,
) {
  const reason = window.prompt("판정 근거를 남겨 주세요.", item.proposalReason);
  if (reason === null) return;
  actionId.value = item.id;
  try {
    await api.resolvePostingDuplicate(item.id, action, canonicalPostingId, reason);
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "중복 판정을 저장하지 못했습니다.";
  } finally {
    actionId.value = null;
  }
}

async function resolveReview(
  item: AssessmentReviewItem,
  action: "APPROVE" | "REJECT",
) {
  const comment = window.prompt("검토 의견을 남겨 주세요.", "") ?? "";
  actionId.value = item.sessionId;
  try {
    await api.resolveAssessmentReview(item.sessionId, action, comment);
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "검토 판정을 저장하지 못했습니다.";
  } finally {
    actionId.value = null;
  }
}

onMounted(load);
</script>

<template>
  <main class="workspace operator-workspace">
    <section class="operator-hero">
      <div>
        <p class="eyebrow">HUMAN REVIEW GATE</p>
        <h1>운영 검토함</h1>
        <p>AI와 규칙이 제안한 판정을 사람이 최종 확정하고 기록합니다.</p>
      </div>
      <button class="icon-button" type="button" title="새로고침" @click="load">
        <RefreshCw :size="18" />
      </button>
    </section>

    <div class="operator-tabs">
      <button :class="{ active: tab === 'POSTINGS' }" @click="tab = 'POSTINGS'">
        공고 중복 {{ duplicates.length }}
      </button>
      <button :class="{ active: tab === 'ASSESSMENTS' }" @click="tab = 'ASSESSMENTS'">
        검증 이의신청 {{ reviews.length }}
      </button>
    </div>

    <p v-if="error" class="inline-error">{{ error }}</p>
    <div v-if="loading" class="state-panel">
      <LoaderCircle class="spin" :size="22" /> 검토 항목을 불러오는 중입니다.
    </div>

    <section v-else-if="tab === 'POSTINGS'" class="operator-list">
      <article v-for="item in duplicates" :key="item.id" class="operator-card">
        <header>
          <span>{{ item.matchKind }}</span>
          <strong>유사도 {{ Math.round(item.similarityScore * 100) }}%</strong>
        </header>
        <div class="operator-comparison">
          <section>
            <small>왼쪽 정본 후보</small>
            <strong>{{ item.left.companyName }}</strong>
            <p>{{ item.left.roleTitle }}</p>
          </section>
          <GitMerge :size="20" />
          <section>
            <small>오른쪽 정본 후보</small>
            <strong>{{ item.right.companyName }}</strong>
            <p>{{ item.right.roleTitle }}</p>
          </section>
        </div>
        <p>{{ item.proposalReason }}</p>
        <div class="operator-actions">
          <button
            class="press-button press-button--primary"
            :disabled="actionId === item.id"
            @click="resolveDuplicate(item, 'MERGE', item.left.id)"
          >
            <GitMerge :size="15" /> 왼쪽으로 합치기
          </button>
          <button
            class="press-button press-button--primary"
            :disabled="actionId === item.id"
            @click="resolveDuplicate(item, 'MERGE', item.right.id)"
          >
            <GitMerge :size="15" /> 오른쪽으로 합치기
          </button>
          <button
            class="press-button press-button--ghost"
            :disabled="actionId === item.id"
            @click="resolveDuplicate(item, 'SEPARATE')"
          >
            <Split :size="15" /> 서로 다른 공고
          </button>
          <button
            class="press-button press-button--ghost"
            :disabled="actionId === item.id"
            @click="resolveDuplicate(item, 'HOLD')"
          >
            <CirclePause :size="15" /> 보류
          </button>
        </div>
      </article>
      <p v-if="!duplicates.length" class="notification-empty">대기 중인 중복 후보가 없습니다.</p>
    </section>

    <section v-else class="operator-list">
      <article v-for="item in reviews" :key="item.sessionId" class="operator-card">
        <header>
          <span><UserRoundCheck :size="15" /> 역량 검증</span>
          <strong>{{ item.averageScore === null ? "점수 없음" : `${Math.round(item.averageScore)}점` }}</strong>
        </header>
        <h2>{{ item.competencyTitle }} · 수준 {{ item.requiredLevel }}</h2>
        <small>{{ item.userEmail }}</small>
        <p>{{ item.appealText }}</p>
        <div class="operator-actions">
          <button
            class="press-button press-button--primary"
            :disabled="actionId === item.sessionId"
            @click="resolveReview(item, 'APPROVE')"
          >
            <Check :size="15" /> 통과 승인
          </button>
          <button
            class="press-button press-button--ghost"
            :disabled="actionId === item.sessionId"
            @click="resolveReview(item, 'REJECT')"
          >
            <X :size="15" /> 원판정 유지
          </button>
        </div>
      </article>
      <p v-if="!reviews.length" class="notification-empty">대기 중인 이의신청이 없습니다.</p>
    </section>
  </main>
</template>
