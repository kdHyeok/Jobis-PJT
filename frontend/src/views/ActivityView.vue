<script setup lang="ts">
import { Bell, Check, Filter, LoaderCircle, RefreshCw, Trash2 } from "@lucide/vue";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import { api } from "@/api";
import { productDialog } from "@/product-dialog";
import AnalysisProgressWheel from "@/components/AnalysisProgressWheel.vue";
import { notificationDestination, notificationTypeLabel } from "@/notification-routing";
import type { ActivityJob, AnalysisJob, CareerSourceSummary, NotificationItem, Posting } from "@/types";

const items = ref<NotificationItem[]>([]);
const unreadCount = ref(0);
const loading = ref(true);
const error = ref("");
const jobs = ref<AnalysisJob[]>([]);
const postings = ref<Posting[]>([]);
const sources = ref<CareerSourceSummary[]>([]);
const auxiliaryJobs = ref<ActivityJob[]>([]);
const hasMoreNotifications = ref(false);
const loadingMore = ref(false);
const unreadOnly = ref(false);
const category = ref("ALL");
const router = useRouter();
let refreshTimer: number | null = null;
const showAnalysisWork = computed(() => ["ALL", "ANALYSIS"].includes(category.value));
const showCareerWork = computed(() => ["ALL", "CAREER"].includes(category.value));
const visibleAuxiliaryJobs = computed(() => auxiliaryJobs.value.filter((job) =>
  ["CHAT", "VERIFICATION"].includes(job.type)
  && (category.value === "ALL" || category.value === job.type),
));

function auxiliaryDestination(job: ActivityJob) {
  if (job.destinationType === "CONVERSATION") return { name: "chat", query: { conversationId: job.destinationId } };
  if (job.destinationType === "POSTING") return { name: "posting-detail", params: { postingId: job.destinationId } };
  if (job.destinationType === "CAREER_SOURCE") return { name: "career-source-review", params: { sourceId: job.destinationId } };
  return { name: "map", query: { node: job.destinationId } };
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("ko-KR", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

async function load(showLoader = true) {
  if (showLoader) loading.value = true;
  error.value = "";
  const results = await Promise.allSettled([
      api.notifications(unreadOnly.value, 30, undefined, undefined, category.value),
      api.analysisJobs("", 30),
      api.postings(),
      api.careerSources(),
      api.activityJobs(),
    ] as const);
  if (results[0].status === "fulfilled") {
    if (showLoader) {
      items.value = results[0].value.items;
    } else {
      const latestIds = new Set(results[0].value.items.map((item) => item.id));
      items.value = [
        ...results[0].value.items,
        ...items.value.filter((item) => !latestIds.has(item.id)),
      ];
    }
    unreadCount.value = results[0].value.unreadCount;
    hasMoreNotifications.value = results[0].value.hasMore;
  }
  if (results[1].status === "fulfilled") {
    jobs.value = results[1].value.filter((job) =>
      ["QUEUED", "RUNNING", "WAITING_FOR_INPUT"].includes(job.status),
    );
  }
  if (results[2].status === "fulfilled") postings.value = results[2].value;
  if (results[3].status === "fulfilled") {
    sources.value = results[3].value.filter((source) => ["QUEUED", "RUNNING"].includes(source.status));
  }
  if (results[4].status === "fulfilled") auxiliaryJobs.value = results[4].value;
  const failed = results.filter((result) => result.status === "rejected").length;
  if (failed) error.value = `일부 활동 정보(${failed}개)를 불러오지 못했습니다.`;
  loading.value = false;
}

async function loadMoreNotifications() {
  const last = items.value[items.value.length - 1];
  if (!last || !hasMoreNotifications.value) return;
  loadingMore.value = true;
  error.value = "";
  try {
    const page = await api.notifications(
      unreadOnly.value,
      30,
      last.createdAt,
      last.id,
      category.value,
    );
    const known = new Set(items.value.map((item) => item.id));
    items.value = [...items.value, ...page.items.filter((item) => !known.has(item.id))];
    hasMoreNotifications.value = page.hasMore;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "이전 알림을 불러오지 못했습니다.";
  } finally {
    loadingMore.value = false;
  }
}

async function open(item: NotificationItem) {
  try {
    if (!item.readAt) {
      await api.readNotification(item.id);
      item.readAt = new Date().toISOString();
      unreadCount.value = Math.max(0, unreadCount.value - 1);
    }
    await router.push(notificationDestination(item));
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "알림을 열지 못했습니다.";
  }
}

async function readAll() {
  error.value = "";
  try {
    await api.readAllNotifications();
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "알림을 모두 읽음 처리하지 못했습니다.";
  }
}

async function deleteOne(item: NotificationItem) {
  error.value = "";
  try {
    await api.deleteNotification(item.id);
    items.value = items.value.filter((candidate) => candidate.id !== item.id);
    if (!item.readAt) unreadCount.value = Math.max(0, unreadCount.value - 1);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "알림을 삭제하지 못했습니다.";
  }
}

async function clearRead() {
  if (!await productDialog.confirm({ title: "읽은 알림 삭제", message: "읽은 알림을 모두 삭제할까요?", confirmLabel: "삭제", danger: true })) return;
  error.value = "";
  try {
    await api.deleteReadNotifications();
    items.value = items.value.filter((item) => !item.readAt);
    await load(false);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "읽은 알림을 정리하지 못했습니다.";
  }
}

function changeFilter() {
  items.value = [];
  hasMoreNotifications.value = false;
  void load();
}

onMounted(() => {
  void load();
  refreshTimer = window.setInterval(() => void load(false), 15000);
});
onBeforeUnmount(() => {
  if (refreshTimer) window.clearInterval(refreshTimer);
});
</script>

<template>
  <main class="workspace activity-workspace">
    <section class="page-heading">
      <div>
        <p class="eyebrow">ACTIVITY</p>
        <h1>알림과 작업 내역</h1>
        <p>공고 분석, 자료 파편화, 증빙 검증과 지도 변경 결과를 확인합니다.</p>
      </div>
      <div class="activity-actions">
        <button class="icon-button" type="button" aria-label="새로고침" @click="load()">
          <RefreshCw :size="18" />
        </button>
        <button
          v-if="unreadCount"
          class="press-button press-button--secondary"
          type="button"
          @click="readAll"
        >
          <Check :size="17" /> 모두 읽음
        </button>
      </div>
    </section>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p>
    <section class="activity-filters" aria-label="활동 필터">
      <Filter :size="17" />
      <label>
        종류
        <select v-model="category" @change="changeFilter">
          <option value="ALL">전체</option>
          <option value="ANALYSIS">공고 분석</option>
          <option value="CAREER">커리어 자료</option>
          <option value="ROADMAP">로드맵</option>
          <option value="VERIFICATION">역량·증거 검증</option>
          <option value="CHAT">AI 대화</option>
        </select>
      </label>
      <label class="activity-unread-toggle">
        <input v-model="unreadOnly" type="checkbox" @change="changeFilter" /> 안 읽은 알림만
      </label>
      <button class="text-action" type="button" @click="clearRead"><Trash2 :size="14" /> 읽은 알림 정리</button>
    </section>
    <div v-if="loading" class="state-panel">
      <LoaderCircle class="spin" :size="24" /> 활동 내역을 불러오는 중입니다.
    </div>
    <template v-else>
    <section v-if="showAnalysisWork && jobs.length" class="activity-running-list">
      <RouterLink
        v-for="job in jobs"
        :key="job.id"
        :to="{ name: 'posting-detail', params: { postingId: job.postingId } }"
      >
        <AnalysisProgressWheel
          compact
          :status="job.status"
          :stage="job.stage"
          :stage-message="job.stageMessage"
          :queue-position="job.queuePosition"
          :events="job.progressEvents"
        />
        <strong>
          {{
            postings.find((posting) => posting.id === job.postingId)?.companyName ??
            "분석 중인 공고"
          }}
        </strong>
      </RouterLink>
    </section>
    <section v-if="showCareerWork && sources.length" class="activity-running-list">
      <RouterLink v-for="source in sources" :key="source.id" :to="{ name: 'career-source-review', params: { sourceId: source.id } }">
        <span class="activity-dot"><LoaderCircle class="spin" :size="17" /></span>
        <span><small>커리어 자료 분석</small><strong>{{ source.title }}</strong><p>{{ source.stageMessage }}</p></span>
      </RouterLink>
    </section>
    <section v-if="visibleAuxiliaryJobs.length" class="activity-running-list">
      <RouterLink v-for="job in visibleAuxiliaryJobs" :key="job.id" :to="auxiliaryDestination(job)">
        <span class="activity-dot"><LoaderCircle class="spin" :size="17" /></span>
        <span><small>{{ job.type === 'CHAT' ? 'AI 답변' : '증거 검증' }}</small><strong>{{ job.title }}</strong><p>{{ job.message }}</p></span>
      </RouterLink>
    </section>
    <section v-if="items.length" class="activity-timeline">
      <article
        v-for="item in items"
        :key="item.id"
        :class="{ unread: !item.readAt }"
      >
        <button type="button" class="activity-timeline__open" @click="open(item)">
          <span class="activity-dot"><Bell :size="16" /></span>
          <span>
            <small>{{ notificationTypeLabel(item.type) }}</small>
            <strong>{{ item.title }}</strong>
            <p>{{ item.body }}</p>
            <time>{{ formatDate(item.createdAt) }}</time>
          </span>
        </button>
        <button class="icon-button activity-timeline__delete" type="button" :aria-label="`${item.title} 알림 삭제`" @click="deleteOne(item)"><Trash2 :size="15" /></button>
      </article>
    </section>
    <button v-if="hasMoreNotifications" class="press-button press-button--ghost activity-load-more" type="button" :disabled="loadingMore" @click="loadMoreNotifications">
      <LoaderCircle v-if="loadingMore" class="spin" :size="16" /> 이전 활동 더 보기
    </button>
    <section
      v-else-if="
        !items.length &&
        (!showAnalysisWork || !jobs.length) &&
        (!showCareerWork || !sources.length) &&
        !visibleAuxiliaryJobs.length
      "
      class="empty-storage"
    >
      <div><Bell :size="28" /></div>
      <h2>아직 활동 내역이 없습니다</h2>
      <p>분석이나 검증이 끝나면 이곳에 기록됩니다.</p>
    </section>
    </template>
  </main>
</template>
