<script setup lang="ts">
import { CircleX, LoaderCircle, MessageCircleMore } from "@lucide/vue";
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api } from "@/api";
import { hasUnreadCompletedReply, markConversationSeen } from "@/conversation-read-state";
import { learningChats } from "@/learning-plan";
import type { ConversationSummary } from "@/types";

const route = useRoute();
const router = useRouter();
const conversations = ref<ConversationSummary[]>([]);
const query = ref("");
const status = ref<"ACTIVE" | "LEARNING">("ACTIVE");
const loading = ref(false);
const error = ref("");
let refreshTimer: number | null = null;

function handleConversationSearch(event: Event) {
  const detail = (event as CustomEvent<{ query?: string }>).detail;
  query.value = detail?.query ?? "";
  void load();
}

function formatTime(value: string | null) {
  if (!value) return "";
  return new Intl.DateTimeFormat("ko-KR", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const page = await api.searchConversations({
      query: query.value.trim(),
      status: "ACTIVE",
      page: 0,
      size: 50,
    });
    conversations.value = page.items.filter((item) =>
      status.value === "LEARNING" ? learningChats.isLearning(item) : !learningChats.isLearning(item)
    );
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "대화 기록을 불러오지 못했습니다.";
  } finally {
    loading.value = false;
  }
}

async function openConversation(id: string) {
  const selected = conversations.value.find((item) => item.id === id);
  if (selected) markConversationSeen(id, selected.lastMessageAt);
  const planId = selected ? learningChats.planIdFor(selected) : null;
  if (planId) {
    await router.push({ name: "learning", params: { planId } });
    return;
  }
  await router.push({ name: "chat", query: { conversationId: id } });
}

watch(status, () => void load());

watch(
  () => route.fullPath,
  () => void load(),
);

onMounted(() => {
  window.addEventListener("jobiss:conversation-search", handleConversationSearch);
  window.addEventListener("jobiss:learning-chats-changed", load);
  void load();
  refreshTimer = window.setInterval(() => void load(), 10_000);
});

onBeforeUnmount(() => {
  window.removeEventListener("jobiss:conversation-search", handleConversationSearch);
  window.removeEventListener("jobiss:learning-chats-changed", load);
  if (refreshTimer) window.clearInterval(refreshTimer);
});
</script>

<template>
  <aside class="conversation-sidebar conversation-sidebar--shelf" aria-label="대화 목록">
    <div class="conversation-status-tabs" role="tablist" aria-label="대화 상태">
      <button
        type="button"
        role="tab"
        :aria-selected="status === 'ACTIVE'"
        :class="{ active: status === 'ACTIVE' }"
        @click="status = 'ACTIVE'"
      >
        진행 중
      </button>
      <button
        type="button"
        role="tab"
        :aria-selected="status === 'LEARNING'"
        :class="{ active: status === 'LEARNING' }"
        @click="status = 'LEARNING'"
      >
        학습 채팅
      </button>
    </div>
    <div class="conversation-list">
      <button
        v-for="item in conversations"
        :key="item.id"
        class="conversation-link conversation-link--shelf"
        :class="{ active: route.query.conversationId === item.id }"
        type="button"
        @click="openConversation(item.id)"
      >
        <span
          class="conversation-state-icon"
          :class="{
            'is-running': item.aiReplyPending,
            'is-failed': !item.aiReplyPending && item.latestJobFailed,
            'is-unread-complete': hasUnreadCompletedReply(item),
          }"
          :title="
            item.aiReplyPending
              ? '답변 생성 중'
              : item.latestJobFailed
                ? '최근 작업 실패'
                : undefined
          "
        >
          <MessageCircleMore :size="17" />
          <LoaderCircle v-if="item.aiReplyPending" class="spin" :size="11" />
          <CircleX v-else-if="item.latestJobFailed" :size="11" />
          <i v-else-if="hasUnreadCompletedReply(item)" aria-label="확인하지 않은 완료 응답" />
        </span>
        <span>
            <strong>{{ learningChats.isLearning(item) ? learningChats.titleFor(item) : item.title }}</strong>
          <small>{{ item.lastMessage || "대화를 시작해 보세요." }}</small>
        </span>
        <time>{{ formatTime(item.lastMessageAt) }}</time>
      </button>
      <div v-if="loading && conversations.length === 0" class="sidebar-empty">불러오는 중…</div>
      <div v-else-if="error" class="sidebar-empty">{{ error }}</div>
      <div v-else-if="conversations.length === 0" class="sidebar-empty">
        {{ status === "LEARNING" ? "아직 시작한 학습 채팅이 없습니다." : "첫 대화를 시작해 보세요." }}
      </div>
    </div>
  </aside>
</template>
