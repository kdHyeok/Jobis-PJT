<script setup lang="ts">
import { Bell, Check, LoaderCircle, RefreshCw } from "@lucide/vue";
import { onMounted, ref } from "vue";

import { api } from "@/api";
import AnalysisProgressWheel from "@/components/AnalysisProgressWheel.vue";
import type { AnalysisJob, NotificationItem, Posting } from "@/types";

const items = ref<NotificationItem[]>([]);
const unreadCount = ref(0);
const loading = ref(true);
const error = ref("");
const jobs = ref<AnalysisJob[]>([]);
const postings = ref<Posting[]>([]);

function formatDate(value: string) {
  return new Intl.DateTimeFormat("ko-KR", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [page, analysisJobs, postingItems] = await Promise.all([
      api.notifications(false),
      api.analysisJobs("", 30),
      api.postings(),
    ]);
    items.value = page.items;
    unreadCount.value = page.unreadCount;
    jobs.value = analysisJobs.filter((job) =>
      ["QUEUED", "RUNNING", "WAITING_FOR_INPUT"].includes(job.status),
    );
    postings.value = postingItems;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "활동 내역을 불러오지 못했습니다.";
  } finally {
    loading.value = false;
  }
}

async function read(item: NotificationItem) {
  if (!item.readAt) {
    await api.readNotification(item.id);
    item.readAt = new Date().toISOString();
    unreadCount.value = Math.max(0, unreadCount.value - 1);
  }
}

async function readAll() {
  await api.readAllNotifications();
  await load();
}

onMounted(load);
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
        <button class="icon-button" type="button" aria-label="새로고침" @click="load">
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
    <p v-if="error" class="form-error">{{ error }}</p>
    <div v-if="loading" class="state-panel">
      <LoaderCircle class="spin" :size="24" /> 활동 내역을 불러오는 중입니다.
    </div>
    <template v-else>
    <section v-if="jobs.length" class="activity-running-list">
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
    <section v-if="items.length" class="activity-timeline">
      <button
        v-for="item in items"
        :key="item.id"
        type="button"
        :class="{ unread: !item.readAt }"
        @click="read(item)"
      >
        <span class="activity-dot"><Bell :size="16" /></span>
        <span>
          <small>{{ item.type }}</small>
          <strong>{{ item.title }}</strong>
          <p>{{ item.body }}</p>
          <time>{{ formatDate(item.createdAt) }}</time>
        </span>
      </button>
    </section>
    <section v-else-if="!jobs.length" class="empty-storage">
      <div><Bell :size="28" /></div>
      <h2>아직 활동 내역이 없습니다</h2>
      <p>분석이나 검증이 끝나면 이곳에 기록됩니다.</p>
    </section>
    </template>
  </main>
</template>
