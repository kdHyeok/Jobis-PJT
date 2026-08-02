<script setup lang="ts">
import { Bell, Check, LoaderCircle, RefreshCw, Sparkles } from "@lucide/vue";
import { computed, onMounted, ref } from "vue";

import { api } from "@/api";
import { showcaseNotifications } from "@/demo/showcase-data";
import type { NotificationItem } from "@/types";

const items = ref<NotificationItem[]>([]);
const unreadCount = ref(0);
const loading = ref(true);
const error = ref("");
const displayItems = computed(() =>
  items.value.length >= 3 ? items.value : showcaseNotifications,
);

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
    const page = await api.notifications(false);
    items.value = page.items;
    unreadCount.value = page.unreadCount;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "활동 내역을 불러오지 못했습니다.";
  } finally {
    loading.value = false;
  }
}

async function read(item: NotificationItem) {
  if (item.id.startsWith("demo-")) {
    item.readAt = item.readAt ?? new Date().toISOString();
    return;
  }
  if (!item.readAt) {
    await api.readNotification(item.id);
    item.readAt = new Date().toISOString();
    unreadCount.value = Math.max(0, unreadCount.value - 1);
  }
}

async function readAll() {
  await api.readAllNotifications();
  await load();
  showcaseNotifications.forEach((item) => {
    item.readAt = item.readAt ?? new Date().toISOString();
  });
}

onMounted(load);
</script>

<template>
  <main class="workspace activity-workspace">
    <section class="activity-hero">
      <div>
        <span class="activity-hero__badge"><Sparkles :size="17" /> MY JOURNEY LOG</span>
        <h1>오늘도 커리어 우주를<br />한 칸 넓혔어요</h1>
        <p>분석과 검증, 로드맵 성장을 시간순으로 모아 보여드려요.</p>
      </div>
      <img src="/img/jobi-mascot.png" alt="활동을 안내하는 펭귄 캐릭터 자비" />
      <div class="activity-hero__count">
        <strong>{{ displayItems.length }}</strong>
        <span>누적 활동</span>
      </div>
    </section>
    <section class="page-heading">
      <div>
        <p class="eyebrow">ACTIVITY</p>
        <h2>알림과 작업 내역</h2>
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
    <section v-else-if="displayItems.length" class="activity-timeline">
      <button
        v-for="item in displayItems"
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
    <section v-else class="empty-storage">
      <div><Bell :size="28" /></div>
      <h2>아직 활동 내역이 없습니다</h2>
      <p>분석이나 검증이 끝나면 이곳에 기록됩니다.</p>
    </section>
  </main>
</template>
