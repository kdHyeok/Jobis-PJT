<script setup lang="ts">
import {
  ArrowLeft,
  Check,
  FileText,
  LoaderCircle,
  Pencil,
  RefreshCw,
  Sparkles,
  Trash2,
} from "@lucide/vue";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api } from "@/api";
import CareerFragmentBody from "@/components/CareerFragmentBody.vue";
import type { CareerFragment, CareerSourceDetail } from "@/types";

const route = useRoute();
const router = useRouter();
const detail = ref<CareerSourceDetail | null>(null);
const selectedIds = ref<string[]>([]);
const loading = ref(true);
const actionLoading = ref(false);
const error = ref("");
const editing = ref<CareerFragment | null>(null);
const editTitle = ref("");
const editDescription = ref("");
let pollTimer: number | null = null;

const sourceId = computed(() => String(route.params.sourceId));
const pending = computed(() =>
  detail.value ? ["QUEUED", "RUNNING"].includes(detail.value.source.status) : false,
);
const visibleFragments = computed(() => {
  if (!detail.value) return [];
  if (detail.value.source.status !== "CONFIRMED") return detail.value.fragments;
  return detail.value.fragments.filter(
    (fragment) => fragment.reviewStatus === "CONFIRMED",
  );
});

async function load() {
  error.value = "";
  try {
    detail.value = await api.careerSource(sourceId.value);
    if (detail.value.source.status === "REVIEW_READY" && !selectedIds.value.length) {
      selectedIds.value = detail.value.fragments
        .filter((fragment) => fragment.reviewStatus === "SUGGESTED")
        .map((fragment) => fragment.id);
    } else if (detail.value.source.status === "CONFIRMED") {
      selectedIds.value = detail.value.fragments
        .filter((fragment) => fragment.reviewStatus === "CONFIRMED")
        .map((fragment) => fragment.id);
    }
    schedulePoll();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "자료를 불러오지 못했습니다.";
  } finally {
    loading.value = false;
  }
}

function schedulePoll() {
  if (pollTimer) window.clearTimeout(pollTimer);
  if (!pending.value) return;
  pollTimer = window.setTimeout(() => void load(), 2500);
}

function beginEdit(fragment: CareerFragment) {
  editing.value = fragment;
  editTitle.value = fragment.title;
  editDescription.value = fragment.description;
}

async function saveEdit() {
  if (!editing.value || !editTitle.value.trim()) return;
  actionLoading.value = true;
  try {
    await api.updateCareerFragment(editing.value.id, {
      kind: editing.value.kind,
      title: editTitle.value.trim(),
      description: editDescription.value.trim(),
      canonicalKey: editing.value.canonicalKey,
      detail: editing.value.detail,
    });
    editing.value = null;
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "조각을 수정하지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

async function remove(fragment: CareerFragment) {
  if (!window.confirm(`“${fragment.title}” 조각을 삭제할까요?`)) return;
  actionLoading.value = true;
  try {
    await api.deleteCareerFragment(fragment.id);
    selectedIds.value = selectedIds.value.filter((id) => id !== fragment.id);
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "조각을 삭제하지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

async function confirm() {
  if (!selectedIds.value.length) return;
  actionLoading.value = true;
  error.value = "";
  try {
    await api.confirmCareerSource(sourceId.value, selectedIds.value);
    await router.push({ name: "storage" });
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "선택한 조각을 저장하지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

async function retry() {
  actionLoading.value = true;
  try {
    await api.retryCareerSource(sourceId.value);
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "분석을 재시도하지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

onMounted(load);
onBeforeUnmount(() => {
  if (pollTimer) window.clearTimeout(pollTimer);
});
</script>

<template>
  <main class="workspace source-review-workspace">
    <RouterLink class="back-link" :to="{ name: 'storage' }">
      <ArrowLeft :size="17" /> 커리어 저장소
    </RouterLink>
    <div v-if="loading" class="state-panel">
      <LoaderCircle class="spin" :size="24" /> 자료를 불러오는 중입니다.
    </div>
    <template v-else-if="detail">
      <section class="page-heading">
        <div>
          <p class="eyebrow">REVIEW EXTRACTION</p>
          <h1>{{ detail.source.title }}</h1>
          <p>{{ detail.source.summary ?? detail.source.stageMessage }}</p>
        </div>
        <span :class="`source-review-status source-review-status--${detail.source.status.toLowerCase()}`">
          <LoaderCircle v-if="pending" class="spin" :size="16" />
          {{ detail.source.stageMessage }}
        </span>
      </section>

      <p v-if="error" class="form-error">{{ error }}</p>

      <section v-if="pending" class="review-pending">
        <Sparkles :size="28" />
        <h2>커리어 조각을 만들고 있어요</h2>
        <p>다른 페이지로 이동해도 분석은 계속되고 완료되면 알림으로 알려드립니다.</p>
      </section>
      <section v-else-if="detail.source.status === 'FAILED'" class="review-pending review-pending--error">
        <h2>자료 분석을 완료하지 못했습니다</h2>
        <p>{{ detail.source.errorMessage }}</p>
        <button
          class="press-button press-button--secondary"
          type="button"
          :disabled="actionLoading || detail.source.attemptCount >= 3"
          @click="retry"
        >
          <RefreshCw :size="17" /> 다시 분석
        </button>
      </section>
      <section v-else class="source-review-grid">
        <article class="source-original">
          <header>
            <FileText :size="19" />
            <div>
              <small>ORIGINAL SOURCE</small>
              <strong>원본 자료</strong>
            </div>
          </header>
          <pre>{{ detail.rawText }}</pre>
        </article>

        <article class="source-suggestions">
          <header>
            <div>
              <small>EXTRACTED FRAGMENTS</small>
              <strong>저장할 조각 선택</strong>
            </div>
            <span>{{ selectedIds.length }} / {{ visibleFragments.length }}</span>
          </header>
          <div class="review-fragment-list">
            <article
              v-for="fragment in visibleFragments"
              :key="fragment.id"
              :class="{ selected: selectedIds.includes(fragment.id) }"
            >
              <label>
                <input
                  v-model="selectedIds"
                  type="checkbox"
                  :value="fragment.id"
                  :disabled="detail.source.status === 'CONFIRMED'"
                />
                <span />
              </label>
              <div>
                <small>{{ fragment.kind }}</small>
                <strong>{{ fragment.title }}</strong>
                <CareerFragmentBody
                  :description="fragment.description"
                  :detail="fragment.detail"
                />
              </div>
              <div v-if="detail.source.status !== 'CONFIRMED'" class="review-fragment-actions">
                <button type="button" aria-label="수정" @click="beginEdit(fragment)">
                  <Pencil :size="15" />
                </button>
                <button type="button" aria-label="삭제" @click="remove(fragment)">
                  <Trash2 :size="15" />
                </button>
              </div>
            </article>
          </div>
          <button
            v-if="detail.source.status !== 'CONFIRMED'"
            class="press-button press-button--primary review-confirm"
            type="button"
            :disabled="actionLoading || !selectedIds.length"
            @click="confirm"
          >
            <Check :size="18" /> 선택한 {{ selectedIds.length }}개 저장
          </button>
          <RouterLink
            v-else
            class="press-button press-button--primary review-confirm"
            :to="{ name: 'storage' }"
          >
            저장소에서 확인
          </RouterLink>
        </article>
      </section>
    </template>

    <button
      v-if="editing"
      class="modal-backdrop"
      type="button"
      aria-label="수정 닫기"
      @click="editing = null"
    />
    <form v-if="editing" class="review-edit-modal" @submit.prevent="saveEdit">
      <p class="eyebrow">EDIT FRAGMENT</p>
      <h2>추출 조각 수정</h2>
      <label>
        제목
        <input v-model="editTitle" required maxlength="180" />
      </label>
      <label>
        설명
        <textarea v-model="editDescription" maxlength="4000" />
      </label>
      <button class="press-button press-button--primary" :disabled="actionLoading">
        <Check :size="17" /> 수정 저장
      </button>
    </form>
  </main>
</template>
