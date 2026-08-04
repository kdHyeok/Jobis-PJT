<script setup lang="ts">
import {
  Archive,
  ArchiveRestore,
  Boxes,
  BriefcaseBusiness,
  Check,
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
import CareerFragmentBody from "@/components/CareerFragmentBody.vue";
import {
  RESUME_ACCEPT,
  RESUME_MIN_CHARS,
  readResumeFile,
  titleFromFileName,
} from "@/resumeFile";
import type {
  CareerFragment,
  CareerFragmentKind,
  CareerSourceSummary,
} from "@/types";

const fragments = ref<CareerFragment[]>([]);
const route = useRoute();
const sources = ref<CareerSourceSummary[]>([]);
const total = ref(0);
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
// docx 원문은 서버가 푼다 — 그동안 sourceText 는 빈 채로 남는다(등록 가드가 이걸 함께 본다).
const fileBase64 = ref("");
const editing = ref<CareerFragment | null>(null);
const merging = ref(false);
const editKind = ref<CareerFragmentKind>("SKILL");
const editTitle = ref("");
const editDescription = ref("");
const editCanonicalKey = ref("");
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
  };
  return labels[source.status];
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [fragmentPage, sourceItems] = await Promise.all([
      api.careerFragments({
        query: query.value.trim(),
        kind: kind.value,
        status: "CONFIRMED",
        sort: sort.value,
        direction: direction.value,
        archived: archived.value,
        size: 100,
      }),
      api.careerSources(false),
    ]);
    fragments.value = fragmentPage.items;
    total.value = fragmentPage.total;
    sources.value = sourceItems;
    selectedIds.value = selectedIds.value.filter((id) =>
      fragmentPage.items.some((fragment) => fragment.id === id),
    );
    schedulePoll();
  } catch (cause) {
    error.value =
      cause instanceof Error ? cause.message : "커리어 저장소를 불러오지 못했습니다.";
  } finally {
    loading.value = false;
  }
}

function schedulePoll() {
  if (pollTimer) window.clearTimeout(pollTimer);
  if (!activeSourceJobs.value.length) return;
  pollTimer = window.setTimeout(() => void load(), 3000);
}

async function readFile(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  error.value = "";
  try {
    const payload = await readResumeFile(file);
    sourceType.value = "FILE";
    fileName.value = payload.fileName;
    sourceTitle.value ||= titleFromFileName(payload.fileName);
    sourceText.value = payload.rawText;
    fileBase64.value = payload.fileBase64 ?? "";
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "파일을 읽지 못했습니다.";
    input.value = "";
  }
}

// docx 는 원문이 서버에서 나오므로 길이로 막을 수 없다 — 파일이 있으면 통과시킨다.
const canCreateSource = computed(
  () =>
    !!sourceTitle.value.trim() &&
    (sourceText.value.trim().length >= RESUME_MIN_CHARS || !!fileBase64.value),
);

async function createSource() {
  if (actionLoading.value || !canCreateSource.value) return;
  actionLoading.value = true;
  error.value = "";
  try {
    const created = await api.createCareerSource({
      sourceType: sourceType.value,
      title: sourceTitle.value.trim(),
      sourceUrl: sourceType.value === "URL" ? sourceUrl.value.trim() : null,
      rawText: sourceText.value.trim(),
      ...(fileBase64.value
        ? { fileBase64: fileBase64.value, fileName: fileName.value }
        : {}),
    });
    showSourceModal.value = false;
    sourceTitle.value = "";
    sourceUrl.value = "";
    sourceText.value = "";
    fileName.value = "";
    fileBase64.value = "";
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

function beginEdit(fragment: CareerFragment) {
  merging.value = false;
  editing.value = fragment;
  editKind.value = fragment.kind;
  editTitle.value = fragment.title;
  editDescription.value = fragment.description;
  editCanonicalKey.value = fragment.canonicalKey ?? "";
}

function beginMerge() {
  const first = selectedFragments.value[0];
  if (!first || selectedFragments.value.length < 2) return;
  merging.value = true;
  editing.value = first;
  editKind.value = first.kind;
  editTitle.value = first.title;
  editDescription.value = selectedFragments.value
    .map((fragment) => fragment.description)
    .filter(Boolean)
    .join("\n");
  editCanonicalKey.value = first.canonicalKey ?? "";
}

async function saveFragment() {
  if (!editing.value || !editTitle.value.trim()) return;
  actionLoading.value = true;
  error.value = "";
  const payload = {
    kind: editKind.value,
    title: editTitle.value.trim(),
    description: editDescription.value.trim(),
    canonicalKey: editCanonicalKey.value.trim() || null,
    detail: editing.value.detail ?? {},
  };
  try {
    if (merging.value) {
      await api.mergeCareerFragments(selectedIds.value, payload);
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
  if (!window.confirm(`“${fragment.title}” 조각을 영구 삭제할까요?`)) return;
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
          <RouterLink
            v-if="['REVIEW_READY', 'CONFIRMED'].includes(source.status)"
            class="text-action"
            :to="{ name: 'career-source-review', params: { sourceId: source.id } }"
          >
            {{ source.status === "REVIEW_READY" ? "조각 검토" : "확인" }}
          </RouterLink>
          <button
            v-else-if="source.status === 'FAILED' && source.attemptCount < 3"
            class="text-action"
            type="button"
            @click="retrySource(source)"
          >
            <RefreshCw :size="14" /> 재시도
          </button>
        </article>
      </div>
    </section>

    <form class="storage-toolbar repository-toolbar" @submit.prevent="load">
      <label class="storage-search">
        <Search :size="18" />
        <input
          v-model="query"
          type="search"
          placeholder="기술, 프로젝트, 교육, 자격 검색"
        />
      </label>
      <select v-model="kind" aria-label="조각 종류" @change="load">
        <option value="">모든 종류</option>
        <option v-for="(meta, value) in kindMeta" :key="value" :value="value">
          {{ meta.label }}
        </option>
      </select>
      <select v-model="sort" aria-label="정렬 기준" @change="load">
        <option value="updatedAt">최근 수정</option>
        <option value="createdAt">등록일</option>
        <option value="title">이름</option>
        <option value="kind">종류</option>
      </select>
      <select v-model="direction" aria-label="정렬 방향" @change="load">
        <option value="desc">내림차순</option>
        <option value="asc">오름차순</option>
      </select>
      <label class="archive-toggle">
        <input v-model="archived" type="checkbox" @change="load" />
        보관함
      </label>
      <button class="icon-button" type="submit" aria-label="검색">
        <Search :size="18" />
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
    <section v-else-if="fragments.length" class="fragment-grid">
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
    <section v-else class="empty-storage">
      <div><BriefcaseBusiness :size="28" /></div>
      <h2>{{ total ? "검색 조건에 맞는 조각이 없습니다" : "저장된 커리어 조각이 없습니다" }}</h2>
      <p>이력서나 프로젝트 설명을 추가하면 AI가 검토할 조각으로 나눕니다.</p>
      <button
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
    <section v-if="showSourceModal" class="posting-modal source-modal">
      <header>
        <div class="modal-icon"><Upload :size="22" /></div>
        <div>
          <p class="eyebrow">ADD CAREER SOURCE</p>
          <h2>커리어 자료 추가</h2>
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
          텍스트 파일
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
        <strong>{{ fileName || "이력서 파일 선택" }}</strong>
        <span>DOCX, TXT, MD · 최대 2MB</span>
        <input type="file" :accept="RESUME_ACCEPT" @change="readFile" />
      </label>
      <label>
        분석할 원문
        <textarea
          v-model="sourceText"
          minlength="20"
          maxlength="100000"
          :placeholder="
            fileBase64
              ? 'docx 원문은 등록할 때 서버가 읽습니다 — 비워 두어도 됩니다.'
              : '이력서, 경력기술서, 프로젝트에서 맡은 역할과 결과를 붙여넣어 주세요.'
          "
        />
        <small>{{ sourceText.length.toLocaleString() }} / 100,000자</small>
      </label>
      <p class="form-hint">
        AI가 자동 저장하지 않습니다. 추출이 끝난 뒤 선택한 조각만 저장됩니다.
      </p>
      <button
        class="press-button press-button--primary modal-submit"
        type="button"
        :disabled="
          actionLoading ||
          !canCreateSource ||
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
        <label>
          정규화 키
          <input
            v-model="editCanonicalKey"
            maxlength="160"
            placeholder="명확한 기술·자격일 때만 사용"
          />
        </label>
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
