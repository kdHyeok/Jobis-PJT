<script setup lang="ts">
import {
  ArrowLeft,
  Check,
  FileText,
  LoaderCircle,
  Pencil,
  Plus,
  RefreshCw,
  Sparkles,
  Trash2,
  X,
} from "@lucide/vue";
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api } from "@/api";
import { productDialog } from "@/product-dialog";
import CareerFragmentBody from "@/components/CareerFragmentBody.vue";
import type { CareerFragment, CareerSourceDetail } from "@/types";

const route = useRoute();
const router = useRouter();
const detail = ref<CareerSourceDetail | null>(null);
const selectedIds = ref<string[]>([]);
const defaultSelectionApplied = ref(false);
const loading = ref(true);
const actionLoading = ref(false);
const error = ref("");
const editing = ref<CareerFragment | null>(null);
const editTitle = ref("");
const editDescription = ref("");
const adding = ref(false);
const addKind = ref<CareerFragment["kind"]>("SKILL");
const addTitle = ref("");
const addDescription = ref("");
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

function kindLabel(kind: CareerFragment["kind"]) {
  return {
    SKILL: "기술",
    PROJECT: "프로젝트",
    EXPERIENCE: "경력",
    EDUCATION: "교육",
    CREDENTIAL: "자격",
    ACHIEVEMENT: "성과",
    LINK: "링크",
  }[kind];
}

async function load() {
  error.value = "";
  try {
    detail.value = await api.careerSource(sourceId.value);
    if (detail.value.source.status === "CONFIRMED") {
      selectedIds.value = detail.value.fragments
        .filter((fragment) => fragment.reviewStatus === "CONFIRMED")
        .map((fragment) => fragment.id);
    } else if (!defaultSelectionApplied.value && detail.value.fragments.length) {
      // 기본은 전부 추가 — 사용자는 뺄 조각(스택·프로젝트 등)만 해제한다.
      // 폴링으로 load 가 반복되므로 최초 도착 때 한 번만 기본값을 깐다.
      selectedIds.value = detail.value.fragments.map((fragment) => fragment.id);
      defaultSelectionApplied.value = true;
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "자료를 불러오지 못했습니다.";
  } finally {
    loading.value = false;
    schedulePoll();
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
  if (!await productDialog.confirm({ title: "커리어 조각 삭제", message: `“${fragment.title}” 조각을 삭제할까요?`, confirmLabel: "삭제", danger: true })) return;
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

async function addFragment() {
  if (!addTitle.value.trim()) return;
  actionLoading.value = true;
  error.value = "";
  try {
    const created = await api.addCareerSourceFragment(sourceId.value, {
      kind: addKind.value,
      title: addTitle.value.trim(),
      description: addDescription.value.trim(),
      detail: {},
    });
    selectedIds.value = [...selectedIds.value, created.id];
    adding.value = false;
    addTitle.value = "";
    addDescription.value = "";
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "조각을 추가하지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

async function deleteSource() {
  const source = detail.value?.source;
  if (!source || !await productDialog.confirm({ title: "원본 자료 영구 삭제", message: `“${source.title}” 원본과 추출 조각을 모두 영구 삭제할까요?`, confirmLabel: "영구 삭제", danger: true })) return;
  actionLoading.value = true;
  error.value = "";
  try {
    await api.deleteCareerSource(source.id);
    await router.push({ name: "storage" });
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "원본 자료를 삭제하지 못했습니다.";
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

async function cancelAnalysis() {
  if (!await productDialog.confirm({ title: "자료 분석 중단", message: "진행 중인 자료 분석을 취소할까요? 원문은 유지됩니다.", confirmLabel: "분석 중단", danger: true })) return;
  actionLoading.value = true;
  error.value = "";
  try {
    await api.cancelCareerSource(sourceId.value);
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "자료 분석을 취소하지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

onMounted(load);
watch(sourceId, () => {
  detail.value = null;
  selectedIds.value = [];
  loading.value = true;
  void load();
});
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
        <div class="source-review-heading-actions">
          <span :class="`source-review-status source-review-status--${detail.source.status.toLowerCase()}`">
            <LoaderCircle v-if="pending" class="spin" :size="16" />
            {{ detail.source.stageMessage }}
          </span>
          <button
            class="press-button press-button--danger"
            type="button"
            :disabled="actionLoading || pending"
            @click="deleteSource"
          >
            <Trash2 :size="16" /> 원본 삭제
          </button>
        </div>
      </section>

      <p v-if="error" class="form-error">{{ error }}</p>

      <section v-if="pending" class="review-pending">
        <Sparkles :size="28" />
        <h2>커리어 조각을 만들고 있어요</h2>
        <p>다른 페이지로 이동해도 분석은 계속되고 완료되면 알림으로 알려드립니다.</p>
        <button class="press-button press-button--ghost" type="button" :disabled="actionLoading" @click="cancelAnalysis">
          <X :size="16" /> 분석 취소
        </button>
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
      <section v-else-if="detail.source.status === 'CANCELLED'" class="review-pending">
        <h2>자료 분석을 취소했습니다</h2>
        <p>원문은 보관되어 있습니다. 필요할 때 같은 자료로 다시 시작할 수 있어요.</p>
        <div class="review-pending__actions">
          <button class="press-button press-button--secondary" type="button" :disabled="actionLoading" @click="retry"><RefreshCw :size="17" /> 다시 분석</button>
          <button class="press-button press-button--danger" type="button" :disabled="actionLoading" @click="deleteSource"><Trash2 :size="16" /> 원본 삭제</button>
        </div>
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
          <div v-if="detail.source.status !== 'CONFIRMED'" class="review-selection-guide">
            <strong>저장할 내용만 직접 선택해 주세요</strong>
            <p>AI 제안은 자동으로 선택되지 않습니다. 빠진 경험은 직접 추가할 수 있습니다.</p>
            <button class="press-button press-button--secondary" type="button" @click="adding = true">
              <Plus :size="16" /> 조각 직접 추가
            </button>
          </div>
          <div class="review-fragment-list">
            <article
              v-for="fragment in visibleFragments"
              :key="fragment.id"
              :class="{ selected: selectedIds.includes(fragment.id) }"
            >
              <label v-if="detail.source.status !== 'CONFIRMED'">
                <input
                  v-model="selectedIds"
                  type="checkbox"
                  :value="fragment.id"
                />
                <span />
              </label>
              <div>
                <small>{{ kindLabel(fragment.kind) }}</small>
                <strong>{{ fragment.title }}</strong>
                <CareerFragmentBody :description="fragment.description" :detail="fragment.detail" />
              </div>
              <span
                v-if="detail.source.status === 'CONFIRMED'"
                class="review-fragment-confirmed"
              >
                <Check :size="14" /> 저장됨
              </span>
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
    <form
      v-if="editing"
      v-dialog-focus="{ onEscape: () => editing = null }"
      class="review-edit-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="fragment-edit-dialog-title"
      tabindex="-1"
      @submit.prevent="saveEdit"
    >
      <p class="eyebrow">EDIT FRAGMENT</p>
      <h2 id="fragment-edit-dialog-title">추출 조각 수정</h2>
      <label>
        제목
        <input v-model="editTitle" required maxlength="180" />
      </label>
      <label>
        설명
        <textarea v-model="editDescription" maxlength="4000" />
      </label>
      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
      <button class="press-button press-button--primary" :disabled="actionLoading">
        <Check :size="17" /> 수정 저장
      </button>
    </form>

    <button
      v-if="adding"
      class="modal-backdrop"
      type="button"
      aria-label="직접 추가 닫기"
      @click="adding = false"
    />
    <form
      v-if="adding"
      v-dialog-focus="{ onEscape: () => adding = false }"
      class="review-edit-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="fragment-add-dialog-title"
      tabindex="-1"
      @submit.prevent="addFragment"
    >
      <button class="modal-close icon-button" type="button" aria-label="닫기" @click="adding = false">
        <X :size="18" />
      </button>
      <p class="eyebrow">ADD FRAGMENT</p>
      <h2 id="fragment-add-dialog-title">빠진 커리어 조각 추가</h2>
      <label>
        종류
        <select v-model="addKind">
          <option value="SKILL">기술</option>
          <option value="PROJECT">프로젝트</option>
          <option value="EXPERIENCE">경력</option>
          <option value="EDUCATION">교육</option>
          <option value="CREDENTIAL">자격</option>
          <option value="ACHIEVEMENT">성과</option>
          <option value="LINK">링크</option>
        </select>
      </label>
      <label>
        제목
        <input v-model="addTitle" required maxlength="180" />
      </label>
      <label>
        설명
        <textarea v-model="addDescription" maxlength="4000" />
      </label>
      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
      <button class="press-button press-button--primary" :disabled="actionLoading || !addTitle.trim()">
        <Plus :size="17" /> 추가하고 선택
      </button>
    </form>
  </main>
</template>
