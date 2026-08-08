<script setup lang="ts">
import {
  Archive,
  ArchiveRestore,
  Boxes,
  BriefcaseBusiness,
  Check,
  ChevronLeft,
  ChevronRight,
  FileText,
  GraduationCap,
  Link2,
  LoaderCircle,
  Merge,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  Trash2,
  Trophy,
  Upload,
  Wrench,
  X,
  type LucideIcon,
} from "@lucide/vue";
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";

import { api } from "@/api";
import { productDialog } from "@/product-dialog";
import CareerFragmentBody from "@/components/CareerFragmentBody.vue";
import type {
  CareerFragment,
  CareerFragmentKind,
  CareerSourceSummary,
} from "@/types";

const fragments = ref<CareerFragment[]>([]);
const route = useRoute();
const sources = ref<CareerSourceSummary[]>([]);
const total = ref(0);
const page = ref(0);
const pageSize = 24;
const loading = ref(true);
const actionLoading = ref(false);
const error = ref("");
const query = ref("");
const kind = ref("");
const sort = ref("updatedAt");
const direction = ref("desc");
const archived = ref(false);
const selectedIds = ref<string[]>([]);
const showSourceModal = ref(false);
const sourceType = ref<"TEXT" | "FILE" | "URL">("TEXT");
const sourceTitle = ref("");
const sourceUrl = ref("");
const sourceText = ref("");
const fileName = ref("");
const selectedFile = ref<File | null>(null);
const editing = ref<CareerFragment | null>(null);
const merging = ref(false);
const editKind = ref<CareerFragmentKind>("SKILL");
const editTitle = ref("");
const editDescription = ref("");
const lastMergeUndoId = ref<string | null>(null);
let pollTimer: number | null = null;

const kindMeta: Record<
  CareerFragmentKind,
  { label: string; icon: LucideIcon }
> = {
  SKILL: { label: "기술", icon: Wrench },
  PROJECT: { label: "프로젝트", icon: Boxes },
  EXPERIENCE: { label: "경력", icon: BriefcaseBusiness },
  EDUCATION: { label: "교육", icon: GraduationCap },
  CREDENTIAL: { label: "자격", icon: Trophy },
  ACHIEVEMENT: { label: "성과", icon: Sparkles },
  LINK: { label: "링크", icon: Link2 },
};

const activeSourceJobs = computed(() =>
  sources.value.filter((source) => ["QUEUED", "RUNNING"].includes(source.status)),
);

const selectedFragments = computed(() =>
  fragments.value.filter((fragment) => selectedIds.value.includes(fragment.id)),
);
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize)));

function formatDate(value: string) {
  return new Intl.DateTimeFormat("ko-KR", {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(new Date(value));
}

function sourceStatus(source: CareerSourceSummary) {
  const labels: Record<CareerSourceSummary["status"], string> = {
    QUEUED: "분석 대기",
    RUNNING: "파편화 중",
    REVIEW_READY: "검토 필요",
    CONFIRMED: "저장 완료",
    FAILED: "분석 실패",
    CANCELLED: "분석 취소",
  };
  return labels[source.status];
}

async function loadFragments(showSpinner = true) {
  if (showSpinner) loading.value = true;
  try {
    const fragmentPage = await api.careerFragments({
      query: query.value.trim(),
      kind: kind.value,
      status: "CONFIRMED",
      sort: sort.value,
      direction: direction.value,
      archived: archived.value,
      page: page.value,
      size: pageSize,
    });
    fragments.value = fragmentPage.items;
    total.value = fragmentPage.total;
    selectedIds.value = selectedIds.value.filter((id) =>
      fragmentPage.items.some((fragment) => fragment.id === id),
    );
  } catch (cause) {
    error.value =
      cause instanceof Error ? cause.message : "커리어 조각을 불러오지 못했습니다.";
  } finally {
    if (showSpinner) loading.value = false;
  }
}

async function refreshSources() {
  try {
    sources.value = await api.careerSources(false);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "원본 자료 상태를 불러오지 못했습니다.";
  } finally {
    schedulePoll();
  }
}

async function load(resetPage = false) {
  if (resetPage) page.value = 0;
  error.value = "";
  await Promise.allSettled([loadFragments(true), refreshSources()]);
}

function schedulePoll() {
  if (pollTimer) window.clearTimeout(pollTimer);
  if (!activeSourceJobs.value.length) return;
  pollTimer = window.setTimeout(() => void refreshSources(), 3000);
}

async function readFile(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  if (file.size > 5 * 1024 * 1024) {
    error.value = "파일은 5MB 이하만 등록할 수 있습니다.";
    input.value = "";
    return;
  }
  if (!/\.(docx|txt|md)$/i.test(file.name)) {
    error.value = "DOCX, TXT, MD 파일만 등록할 수 있습니다.";
    input.value = "";
    return;
  }
  sourceType.value = "FILE";
  fileName.value = file.name;
  selectedFile.value = file;
  sourceTitle.value ||= file.name.replace(/\.[^.]+$/, "");
}

async function createSource() {
  if (
    actionLoading.value ||
    !sourceTitle.value.trim() ||
    (sourceType.value === "FILE"
      ? !selectedFile.value
      : sourceText.value.trim().length < 20)
  ) return;
  actionLoading.value = true;
  error.value = "";
  try {
    const created = sourceType.value === "FILE" && selectedFile.value
      ? await api.uploadCareerSource(selectedFile.value, sourceTitle.value.trim())
      : await api.createCareerSource({
          sourceType: sourceType.value,
          title: sourceTitle.value.trim(),
          sourceUrl: sourceType.value === "URL" ? sourceUrl.value.trim() : null,
          rawText: sourceText.value.trim(),
        });
    showSourceModal.value = false;
    sourceTitle.value = "";
    sourceUrl.value = "";
    sourceText.value = "";
    fileName.value = "";
    selectedFile.value = null;
    await load();
    sources.value = [
      created.source,
      ...sources.value.filter((source) => source.id !== created.source.id),
    ];
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "자료를 등록하지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

async function retrySource(source: CareerSourceSummary) {
  actionLoading.value = true;
  error.value = "";
  try {
    await api.retryCareerSource(source.id);
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "분석을 재시도하지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

async function removeSource(source: CareerSourceSummary) {
  if (!await productDialog.confirm({ title: "원본 자료 영구 삭제", message: `“${source.title}” 원본과 여기서 추출된 조각을 모두 삭제할까요? 이 작업은 되돌릴 수 없습니다.`, confirmLabel: "영구 삭제", danger: true })) {
    return;
  }
  actionLoading.value = true;
  error.value = "";
  try {
    await api.deleteCareerSource(source.id);
    await Promise.allSettled([loadFragments(false), refreshSources()]);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "원본 자료를 삭제하지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

function beginEdit(fragment: CareerFragment) {
  merging.value = false;
  editing.value = fragment;
  editKind.value = fragment.kind;
  editTitle.value = fragment.title;
  editDescription.value = fragment.description;
}

async function beginMerge() {
  const first = selectedFragments.value[0];
  if (!first || selectedFragments.value.length < 2) return;
  if (selectedFragments.value.some((fragment) => fragment.kind !== first.kind)) {
    error.value = "같은 종류의 커리어 조각만 병합할 수 있습니다.";
    return;
  }
  const preview = await api.previewCareerFragmentMerge(selectedIds.value);
  if (!preview.compatible) {
    error.value = preview.reason;
    return;
  }
  if (!await productDialog.confirm({ title: "커리어 조각 병합", message: `${selectedFragments.value.length}개 조각을 하나로 합칩니다.\n${preview.reason}`, confirmLabel: "병합" })) {
    return;
  }
  merging.value = true;
  editing.value = first;
  editKind.value = first.kind;
  editTitle.value = first.title;
  editDescription.value = selectedFragments.value
    .map((fragment) => fragment.description)
    .filter(Boolean)
    .join("\n");
}

async function saveFragment() {
  if (!editing.value || !editTitle.value.trim()) return;
  actionLoading.value = true;
  error.value = "";
  const payload = {
    kind: editKind.value,
    title: editTitle.value.trim(),
    description: editDescription.value.trim(),
    canonicalKey: editing.value.canonicalKey,
    detail: editing.value.detail ?? {},
  };
  try {
    if (merging.value) {
      const merged = await api.mergeCareerFragments(selectedIds.value, payload);
      lastMergeUndoId.value = merged.undoId;
      selectedIds.value = [];
    } else {
      await api.updateCareerFragment(editing.value.id, payload);
    }
    editing.value = null;
    merging.value = false;
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "커리어 조각을 저장하지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

async function toggleArchive(fragment: CareerFragment) {
  actionLoading.value = true;
  error.value = "";
  try {
    if (fragment.archivedAt) await api.restoreCareerFragment(fragment.id);
    else await api.archiveCareerFragment(fragment.id);
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "보관 상태를 변경하지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

async function removeFragment(fragment: CareerFragment) {
  if (!await productDialog.confirm({ title: "커리어 조각 영구 삭제", message: `“${fragment.title}” 조각을 영구 삭제할까요?`, confirmLabel: "영구 삭제", danger: true })) return;
  actionLoading.value = true;
  error.value = "";
  try {
    await api.deleteCareerFragment(fragment.id);
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "조각을 삭제하지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

async function undoLastMerge() {
  if (!lastMergeUndoId.value || actionLoading.value) return;
  actionLoading.value = true;
  error.value = "";
  try {
    await api.undoCareerFragmentMerge(lastMergeUndoId.value);
    lastMergeUndoId.value = null;
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "병합을 되돌리지 못했습니다.";
  } finally {
    actionLoading.value = false;
  }
}

watch(
  () => route.query.add,
  (value) => {
    if (value === "1") showSourceModal.value = true;
  },
);

onMounted(() => {
  if (route.query.add === "1") showSourceModal.value = true;
  void load();
});
onBeforeUnmount(() => {
  if (pollTimer) window.clearTimeout(pollTimer);
});
</script>

<template>
  <main class="workspace repository-workspace">
    <section class="page-heading">
      <div>
        <p class="eyebrow">CAREER REPOSITORY</p>
        <h1>커리어 저장소</h1>
        <p>이력서와 경험 자료를 검토 가능한 기술·프로젝트·경력 조각으로 정리합니다.</p>
      </div>
      <button
        class="press-button press-button--primary"
        type="button"
        @click="showSourceModal = true"
      >
        <Plus :size="18" /> 자료 추가
      </button>
    </section>

    <section v-if="lastMergeUndoId" class="inline-notice inline-notice--success" role="status">
      <span>커리어 조각을 병합했습니다. 원본 조각은 안전하게 보관되어 있습니다.</span>
      <button class="text-button" type="button" :disabled="actionLoading" @click="undoLastMerge">병합 되돌리기</button>
    </section>

    <section v-if="sources.length" class="source-rail">
      <header>
        <div>
          <p class="eyebrow">SOURCE PROCESSING</p>
          <h2>등록한 원본 자료</h2>
        </div>
        <span>{{ sources.length }}개</span>
      </header>
      <div class="source-rail__list">
        <article
          v-for="source in sources"
          :key="source.id"
          class="source-card"
          :class="`source-card--${source.status.toLowerCase()}`"
        >
          <span class="source-card__icon">
            <LoaderCircle
              v-if="['QUEUED', 'RUNNING'].includes(source.status)"
              class="spin"
              :size="20"
            />
            <FileText v-else :size="20" />
          </span>
          <div>
            <small>{{ sourceStatus(source) }}</small>
            <strong>{{ source.title }}</strong>
            <p>{{ source.stageMessage }}</p>
          </div>
          <div
            v-if="!['QUEUED', 'RUNNING'].includes(source.status)"
            class="source-card__actions"
          >
            <RouterLink
              v-if="['REVIEW_READY', 'CONFIRMED'].includes(source.status)"
              class="text-action"
              :to="{ name: 'career-source-review', params: { sourceId: source.id } }"
            >
              {{ source.status === "REVIEW_READY" ? "조각 검토" : "확인" }}
            </RouterLink>
            <RouterLink
              v-if="source.status === 'CONFIRMED'"
              class="text-action"
              :to="{
                name: 'chat',
                query: { mode: 'RESUME_DIAGNOSIS', source: source.id },
              }"
            >
              <Sparkles :size="14" /> AI 진단
            </RouterLink>
            <button
              v-if="source.status === 'FAILED' && source.attemptCount < 3"
              class="text-action"
              type="button"
              @click="retrySource(source)"
            >
              <RefreshCw :size="14" /> 재시도
            </button>
            <button
              class="text-action text-action--danger"
              type="button"
              :disabled="actionLoading"
              :aria-label="`${source.title} 원본 삭제`"
              title="원본과 파생 조각 삭제"
              @click="removeSource(source)"
            >
              원본 삭제
            </button>
          </div>
        </article>
      </div>
    </section>

    <form class="storage-toolbar repository-toolbar" @submit.prevent="load(true)">
      <label class="storage-search">
        <Search :size="18" />
        <input
          v-model="query"
          type="search"
          placeholder="기술, 프로젝트, 교육, 자격 검색"
        />
      </label>
      <select v-model="kind" aria-label="조각 종류" @change="load(true)">
        <option value="">모든 종류</option>
        <option v-for="(meta, value) in kindMeta" :key="value" :value="value">
          {{ meta.label }}
        </option>
      </select>
      <select v-model="sort" aria-label="정렬 기준" @change="load(true)">
        <option value="updatedAt">최근 수정</option>
        <option value="createdAt">등록일</option>
        <option value="title">이름</option>
        <option value="kind">종류</option>
      </select>
      <select v-model="direction" aria-label="정렬 방향" @change="load(true)">
        <option value="desc">내림차순</option>
        <option value="asc">오름차순</option>
      </select>
      <label class="archive-toggle">
        <input v-model="archived" type="checkbox" @change="load(true)" />
        보관함
      </label>
      <button class="press-button press-button--secondary storage-search-submit" type="submit">
        <Search :size="17" /> 검색
      </button>
    </form>

    <div v-if="selectedIds.length" class="selection-bar">
      <strong>{{ selectedIds.length }}개 선택</strong>
      <button
        class="press-button press-button--secondary"
        type="button"
        :disabled="selectedIds.length < 2"
        @click="beginMerge"
      >
        <Merge :size="16" /> 하나로 병합
      </button>
      <button class="text-action" type="button" @click="selectedIds = []">
        선택 해제
      </button>
    </div>

    <p v-if="error" class="form-error storage-error">{{ error }}</p>
    <div v-if="loading" class="state-panel">
      <LoaderCircle class="spin" :size="24" />
      저장한 커리어 조각을 불러오는 중입니다.
    </div>
    <template v-else-if="fragments.length">
      <section class="fragment-grid">
        <article
          v-for="fragment in fragments"
          :key="fragment.id"
          class="fragment-card"
          :class="{ selected: selectedIds.includes(fragment.id) }"
        >
        <label class="fragment-select">
          <input v-model="selectedIds" type="checkbox" :value="fragment.id" />
          <span>선택</span>
        </label>
        <span class="fragment-kind">
          <component :is="kindMeta[fragment.kind].icon" :size="17" />
          {{ kindMeta[fragment.kind].label }}
        </span>
        <h2>{{ fragment.title }}</h2>
        <CareerFragmentBody :description="fragment.description" :detail="fragment.detail" />
        <small>{{ fragment.sourceTitle }} · {{ formatDate(fragment.updatedAt) }}</small>
        <footer>
          <button class="text-action" type="button" @click="beginEdit(fragment)">
            <Pencil :size="14" /> 수정
          </button>
          <button class="text-action" type="button" @click="toggleArchive(fragment)">
            <ArchiveRestore v-if="fragment.archivedAt" :size="14" />
            <Archive v-else :size="14" />
            {{ fragment.archivedAt ? "복원" : "보관" }}
          </button>
          <button
            class="text-action text-action--danger"
            type="button"
            @click="removeFragment(fragment)"
          >
            <Trash2 :size="14" /> 삭제
          </button>
        </footer>
        </article>
      </section>
      <nav v-if="total > pageSize" class="pagination" aria-label="커리어 조각 페이지">
        <button
          class="icon-button"
          type="button"
          :disabled="page === 0"
          aria-label="이전 페이지"
          @click="page -= 1; loadFragments()"
        >
          <ChevronLeft :size="19" />
        </button>
        <span>{{ page + 1 }} / {{ pageCount }} · 총 {{ total }}개</span>
        <button
          class="icon-button"
          type="button"
          :disabled="page + 1 >= pageCount"
          aria-label="다음 페이지"
          @click="page += 1; loadFragments()"
        >
          <ChevronRight :size="19" />
        </button>
      </nav>
    </template>
    <section v-else class="empty-storage">
      <div><BriefcaseBusiness :size="28" /></div>
      <h2>
        {{
          query.trim() || kind || archived
            ? "검색 조건에 맞는 조각이 없습니다"
            : sources.length
              ? "확정된 커리어 조각이 없습니다"
              : "저장된 커리어 조각이 없습니다"
        }}
      </h2>
      <p v-if="sources.length">
        분석 결과를 검토하고 저장할 조각을 확정하면 이곳에 표시됩니다.
      </p>
      <p v-else>이력서나 프로젝트 설명을 추가하면 AI가 검토할 조각으로 나눕니다.</p>
      <button
        v-if="!sources.length"
        class="press-button press-button--primary"
        type="button"
        @click="showSourceModal = true"
      >
        첫 자료 등록하기
      </button>
    </section>

    <button
      v-if="showSourceModal"
      class="modal-backdrop"
      type="button"
      aria-label="자료 추가 닫기"
      @click="showSourceModal = false"
    />
    <section
      v-if="showSourceModal"
      v-dialog-focus="{ onEscape: () => showSourceModal = false }"
      class="posting-modal source-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="storage-source-dialog-title"
      tabindex="-1"
    >
      <header>
        <div class="modal-icon"><Upload :size="22" /></div>
        <div>
          <p class="eyebrow">ADD CAREER SOURCE</p>
          <h2 id="storage-source-dialog-title">커리어 자료 추가</h2>
        </div>
        <button class="icon-button" type="button" @click="showSourceModal = false">
          <X :size="20" />
        </button>
      </header>
      <div class="source-tabs">
        <button
          type="button"
          :class="{ active: sourceType === 'TEXT' }"
          @click="sourceType = 'TEXT'"
        >
          텍스트 붙여넣기
        </button>
        <button
          type="button"
          :class="{ active: sourceType === 'FILE' }"
          @click="sourceType = 'FILE'"
        >
          파일 업로드
        </button>
        <button
          type="button"
          :class="{ active: sourceType === 'URL' }"
          @click="sourceType = 'URL'"
        >
          URL 자료
        </button>
      </div>
      <label>
        자료 이름
        <input
          v-model="sourceTitle"
          maxlength="180"
          placeholder="예: 2026 백엔드 이력서"
        />
      </label>
      <label v-if="sourceType === 'URL'">
        원본 URL
        <input v-model="sourceUrl" type="url" placeholder="https://…" />
      </label>
      <label v-if="sourceType === 'FILE'" class="file-drop">
        <Upload :size="22" />
        <strong>{{ fileName || "이력서·경력 파일 선택" }}</strong>
        <span>DOCX, TXT, MD · 최대 5MB</span>
        <input
          type="file"
          accept=".docx,.txt,.md,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/markdown"
          @change="readFile"
        />
      </label>
      <label v-if="sourceType !== 'FILE'">
        분석할 원문
        <textarea
          v-model="sourceText"
          minlength="20"
          maxlength="100000"
          placeholder="이력서, 경력기술서, 프로젝트에서 맡은 역할과 결과를 붙여넣어 주세요."
        />
        <small>{{ sourceText.length.toLocaleString() }} / 100,000자</small>
      </label>
      <p class="form-hint">
        AI가 자동 저장하지 않습니다. 추출이 끝난 뒤 선택한 조각만 저장됩니다.
      </p>
      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
      <button
        class="press-button press-button--primary modal-submit"
        type="button"
        :disabled="
          actionLoading ||
          !sourceTitle.trim() ||
          (sourceType === 'FILE' ? !selectedFile : sourceText.trim().length < 20) ||
          (sourceType === 'URL' && !sourceUrl.trim())
        "
        @click="createSource"
      >
        <LoaderCircle v-if="actionLoading" class="spin" :size="18" />
        <Sparkles v-else :size="18" />
        파편화 시작
      </button>
    </section>

    <button
      v-if="editing"
      class="drawer-backdrop"
      type="button"
      aria-label="조각 편집 닫기"
      @click="editing = null"
    />
    <aside v-if="editing" class="detail-drawer fragment-editor">
      <div class="drawer-top">
        <span class="drawer-icon">
          <Merge v-if="merging" :size="22" />
          <Pencil v-else :size="22" />
        </span>
        <button class="icon-button" type="button" @click="editing = null">
          <X :size="20" />
        </button>
      </div>
      <p class="eyebrow">{{ merging ? "MERGE FRAGMENTS" : "EDIT FRAGMENT" }}</p>
      <h2>{{ merging ? `${selectedIds.length}개 조각 병합` : "커리어 조각 수정" }}</h2>
      <form class="fragment-form" @submit.prevent="saveFragment">
        <label>
          종류
          <select v-model="editKind">
            <option v-for="(meta, value) in kindMeta" :key="value" :value="value">
              {{ meta.label }}
            </option>
          </select>
        </label>
        <label>
          제목
          <input v-model="editTitle" required maxlength="180" />
        </label>
        <label>
          설명
          <textarea v-model="editDescription" maxlength="4000" />
        </label>
        <p v-if="merging" class="form-hint">
          같은 종류의 조각만 병합되며 기술 식별 정보는 시스템이 유지합니다.
        </p>
        <p v-if="error" class="form-error" role="alert">{{ error }}</p>
        <button
          class="press-button press-button--primary"
          type="submit"
          :disabled="actionLoading || !editTitle.trim()"
        >
          <Check :size="17" /> {{ merging ? "병합해서 저장" : "수정 저장" }}
        </button>
      </form>
    </aside>
  </main>
</template>
