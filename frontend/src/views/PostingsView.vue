<script setup lang="ts">
import {
  Archive,
  ArchiveRestore,
  BriefcaseBusiness,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  CircleHelp,
  Edit3,
  ExternalLink,
  FileSearch,
  LoaderCircle,
  RefreshCw,
  Search,
  Trash2,
  X,
} from "@lucide/vue";
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import { api } from "@/api";
import type { Posting, PostingDetail, PostingPage } from "@/types";

const result = ref<PostingPage>({ items: [], page: 0, size: 20, total: 0 });
const router = useRouter();
const query = ref("");
const status = ref("");
const sort = ref("createdAt");
const direction = ref("desc");
const archived = ref(false);
const page = ref(0);
const loading = ref(true);
const actionId = ref<string | null>(null);
const error = ref("");
const selected = ref<PostingDetail | null>(null);
const editing = ref(false);
const editUrl = ref("");
const editRawText = ref("");

const pageCount = computed(() => Math.max(1, Math.ceil(result.value.total / result.value.size)));

function statusLabel(value: string | null) {
  const labels: Record<string, string> = {
    QUEUED: "분석 대기",
    RUNNING: "분석 중",
    WAITING_FOR_INPUT: "답변 필요",
    SUCCEEDED: "분석 완료",
    FAILED: "분석 실패",
  };
  return value ? labels[value] ?? value : "등록됨";
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("ko-KR", {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(new Date(value));
}

async function load(resetPage = false) {
  if (resetPage) page.value = 0;
  loading.value = true;
  error.value = "";
  try {
    result.value = await api.searchPostings({
      query: query.value.trim(),
      status: status.value,
      sort: sort.value,
      direction: direction.value,
      page: page.value,
      size: 20,
      archived: archived.value,
    });
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "저장소를 불러오지 못했습니다.";
  } finally {
    loading.value = false;
  }
}

async function open(posting: Posting) {
  await router.push({ name: "posting-detail", params: { postingId: posting.id } });
}

async function updatePosting() {
  if (!selected.value) return;
  actionId.value = selected.value.id;
  error.value = "";
  try {
    await api.updatePosting(
      selected.value.id,
      editUrl.value.trim() || null,
      editRawText.value.trim(),
    );
    selected.value = await api.posting(selected.value.id);
    editing.value = false;
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "공고를 수정하지 못했습니다.";
  } finally {
    actionId.value = null;
  }
}

async function archivePosting(posting: PostingDetail | Posting) {
  actionId.value = posting.id;
  error.value = "";
  try {
    if (posting.archivedAt) await api.restorePosting(posting.id);
    else await api.archivePosting(posting.id);
    selected.value = null;
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "보관 상태를 변경하지 못했습니다.";
  } finally {
    actionId.value = null;
  }
}

async function deletePosting(posting: PostingDetail | Posting) {
  if (
    !window.confirm(
      "이 공고와 분석 기록을 영구 삭제할까요? 이미 지도에 반영된 공고는 삭제할 수 없습니다.",
    )
  ) return;
  actionId.value = posting.id;
  error.value = "";
  try {
    await api.deletePosting(posting.id);
    selected.value = null;
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "공고를 삭제하지 못했습니다.";
  } finally {
    actionId.value = null;
  }
}

async function retry(posting: PostingDetail | Posting) {
  if (!posting.analysisJobId) return;
  actionId.value = posting.id;
  error.value = "";
  try {
    await api.retryAnalysis(posting.analysisJobId);
    if (selected.value) selected.value = await api.posting(selected.value.id);
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "분석을 재시도하지 못했습니다.";
  } finally {
    actionId.value = null;
  }
}

async function movePage(next: number) {
  page.value = Math.min(Math.max(0, next), pageCount.value - 1);
  await load();
}

onMounted(() => load());
</script>

<template>
  <main class="workspace storage-workspace">
    <section class="page-heading">
      <div>
        <p class="eyebrow">JOB POSTINGS</p>
        <h1>채용 공고</h1>
        <p>등록한 공고의 원문, 분석 상태와 결과를 다시 찾고 관리합니다.</p>
      </div>
      <RouterLink class="press-button press-button--primary" :to="{ name: 'posting-new' }">
        <BriefcaseBusiness :size="18" />
        새 공고 분석
      </RouterLink>
    </section>

    <form class="storage-toolbar" @submit.prevent="load(true)">
      <label class="storage-search">
        <Search :size="18" />
        <input v-model="query" type="search" placeholder="회사, 직무, 경력 조건 검색" />
      </label>
      <select v-model="status" aria-label="분석 상태" @change="load(true)">
        <option value="">모든 분석 상태</option>
        <option value="QUEUED">분석 대기</option>
        <option value="RUNNING">분석 중</option>
        <option value="WAITING_FOR_INPUT">답변 필요</option>
        <option value="SUCCEEDED">분석 완료</option>
        <option value="FAILED">분석 실패</option>
      </select>
      <select v-model="sort" aria-label="정렬 기준" @change="load(true)">
        <option value="createdAt">등록일</option>
        <option value="updatedAt">수정일</option>
        <option value="companyName">회사명</option>
        <option value="roleTitle">직무명</option>
      </select>
      <select v-model="direction" aria-label="정렬 방향" @change="load(true)">
        <option value="desc">내림차순</option>
        <option value="asc">오름차순</option>
      </select>
      <label class="archive-toggle">
        <input v-model="archived" type="checkbox" @change="load(true)" />
        보관함 보기
      </label>
      <button class="icon-button" type="submit" aria-label="검색">
        <Search :size="18" />
      </button>
    </form>

    <p v-if="error" class="form-error storage-error">{{ error }}</p>
    <div v-if="loading" class="state-panel">
      <LoaderCircle class="spin" :size="24" />
      저장한 공고를 불러오는 중입니다.
    </div>
    <div v-else-if="result.items.length === 0" class="empty-storage">
      <div><FileSearch :size="28" /></div>
      <h2>{{ archived ? "보관된 공고가 없습니다" : "조건에 맞는 공고가 없습니다" }}</h2>
      <p>새 공고를 대화에 첨부하거나 검색 조건을 바꿔 보세요.</p>
      <RouterLink class="press-button press-button--primary" :to="{ name: 'posting-new' }">
        첫 공고 분석하기
      </RouterLink>
    </div>

    <section v-else class="storage-list">
      <button
        v-for="posting in result.items"
        :key="posting.id"
        class="storage-item"
        type="button"
        @click="open(posting)"
      >
        <span class="storage-logo">
          {{ posting.companyName?.slice(0, 1) ?? "?" }}
        </span>
        <span class="storage-copy">
          <small>{{ posting.companyName ?? "회사명 분석 중" }}</small>
          <strong>{{ posting.roleTitle ?? "직무를 분석하고 있습니다" }}</strong>
          <span>{{ posting.experienceText ?? "경력 조건 미확인" }} · {{ formatDate(posting.createdAt) }}</span>
        </span>
        <span :class="`posting-status posting-status--${(posting.analysisStatus ?? 'saved').toLowerCase()}`">
          <LoaderCircle
            v-if="['QUEUED', 'RUNNING'].includes(posting.analysisStatus ?? '')"
            class="spin"
            :size="14"
          />
          <CircleAlert v-else-if="posting.analysisStatus === 'FAILED'" :size="14" />
          <CircleHelp
            v-else-if="posting.analysisStatus === 'WAITING_FOR_INPUT'"
            :size="14"
          />
          {{ statusLabel(posting.analysisStatus) }}
        </span>
        <ChevronRight :size="20" />
      </button>
    </section>

    <nav v-if="result.total > result.size" class="pagination" aria-label="페이지">
      <button
        class="icon-button"
        type="button"
        :disabled="page === 0"
        @click="movePage(page - 1)"
      >
        <ChevronLeft :size="19" />
      </button>
      <span>{{ page + 1 }} / {{ pageCount }} · 총 {{ result.total }}개</span>
      <button
        class="icon-button"
        type="button"
        :disabled="page + 1 >= pageCount"
        @click="movePage(page + 1)"
      >
        <ChevronRight :size="19" />
      </button>
    </nav>

    <button
      v-if="selected"
      class="drawer-backdrop"
      type="button"
      aria-label="공고 상세 닫기"
      @click="selected = null"
    />
    <aside v-if="selected" class="detail-drawer storage-drawer">
      <div class="drawer-top">
        <span class="drawer-icon">{{ selected.companyName?.slice(0, 1) ?? "?" }}</span>
        <button class="icon-button" type="button" @click="selected = null">
          <X :size="20" />
        </button>
      </div>
      <p class="eyebrow">{{ selected.companyName ?? "분석 전 공고" }}</p>
      <h2>{{ selected.roleTitle ?? "직무 정보 미확인" }}</h2>
      <p class="drawer-subtitle">
        {{ selected.experienceText ?? "경력 조건 미확인" }}
        <template v-if="selected.employmentType"> · {{ selected.employmentType }}</template>
      </p>

      <div class="drawer-action-grid">
        <button
          v-if="selected.analysisStatus === 'FAILED'"
          class="press-button press-button--secondary"
          type="button"
          :disabled="actionId === selected.id"
          @click="retry(selected)"
        >
          <RefreshCw :size="16" /> 분석 재시도
        </button>
        <button class="press-button press-button--ghost" type="button" @click="editing = !editing">
          <Edit3 :size="16" /> {{ editing ? "수정 취소" : "원문 수정" }}
        </button>
        <button
          class="press-button press-button--ghost"
          type="button"
          :disabled="actionId === selected.id"
          @click="archivePosting(selected)"
        >
          <ArchiveRestore v-if="selected.archivedAt" :size="16" />
          <Archive v-else :size="16" />
          {{ selected.archivedAt ? "복원" : "보관" }}
        </button>
        <button
          class="press-button press-button--danger"
          type="button"
          :disabled="actionId === selected.id"
          @click="deletePosting(selected)"
        >
          <Trash2 :size="16" /> 삭제
        </button>
      </div>

      <form v-if="editing" class="posting-edit-form" @submit.prevent="updatePosting">
        <label>
          공고 URL
          <input v-model="editUrl" type="url" maxlength="2000" />
        </label>
        <label>
          공고 원문
          <textarea v-model="editRawText" required minlength="20" maxlength="100000" />
        </label>
        <p>저장하면 기존 분석 결과 대신 새 분석 작업이 시작됩니다.</p>
        <button
          class="press-button press-button--primary"
          type="submit"
          :disabled="actionId === selected.id || editRawText.trim().length < 20"
        >
          <LoaderCircle v-if="actionId === selected.id" class="spin" :size="17" />
          <RefreshCw v-else :size="17" />
          수정하고 다시 분석
        </button>
      </form>

      <template v-else>
        <section>
          <h3>분석 상태</h3>
          <span :class="`posting-status posting-status--${(selected.analysisStatus ?? 'saved').toLowerCase()}`">
            {{ statusLabel(selected.analysisStatus) }}
          </span>
        </section>
        <section v-if="selected.sourceUrl">
          <h3>원본 링크</h3>
          <a :href="selected.sourceUrl" target="_blank" rel="noopener noreferrer">
            링크 열기 <ExternalLink :size="14" />
          </a>
        </section>
        <section>
          <h3>공고 원문</h3>
          <pre class="posting-raw-text">{{ selected.rawText }}</pre>
        </section>
      </template>
    </aside>
  </main>
</template>
