<script setup lang="ts">
import {
  Activity,
  Archive,
  Bell,
  BriefcaseBusiness,
  Check,
  House,
  LogOut,
  Map,
  MessageCircle,
  Orbit,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Settings,
} from "@lucide/vue";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { RouterLink, RouterView, useRoute, useRouter } from "vue-router";

import { api } from "@/api";
import { session } from "@/session";
import type { NotificationItem } from "@/types";

const router = useRouter();
const route = useRoute();
const initial = computed(() => session.user.value?.displayName.slice(0, 1) ?? "J");
const notifications = ref<NotificationItem[]>([]);
const unreadCount = ref(0);
const showNotifications = ref(false);
const headerError = ref("");
const sidebarCollapsed = ref(window.localStorage.getItem("jobis:sidebar-collapsed") === "1");
let notificationTimer: number | null = null;

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value;
  window.localStorage.setItem("jobis:sidebar-collapsed", sidebarCollapsed.value ? "1" : "0");
}

function sectionActive(section: string) {
  if (section === "/app") return route.path === section;
  return route.path === section || route.path.startsWith(`${section}/`);
}

function formatTime(value: string) {
  const seconds = Math.floor((Date.now() - new Date(value).getTime()) / 1000);
  if (seconds < 60) return "방금";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}분 전`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}시간 전`;
  return `${Math.floor(seconds / 86400)}일 전`;
}

async function loadNotifications() {
  try {
    const result = await api.notifications();
    notifications.value = result.items;
    unreadCount.value = result.unreadCount;
  } catch {
    // 알림 폴링 실패가 주요 작업을 막지 않도록 다음 주기에 재시도한다.
  }
}

async function openNotification(item: NotificationItem) {
  if (!item.readAt) {
    await api.readNotification(item.id);
    item.readAt = new Date().toISOString();
    unreadCount.value = Math.max(0, unreadCount.value - 1);
  }
  showNotifications.value = false;
  const analysisJobId =
    typeof item.payload.analysisJobId === "string" ? item.payload.analysisJobId : null;
  const postingId =
    typeof item.payload.postingId === "string" ? item.payload.postingId : null;
  const careerSourceId =
    typeof item.payload.careerSourceId === "string"
      ? item.payload.careerSourceId
      : null;
  if (careerSourceId) {
    await router.push({
      name: "career-source-review",
      params: { sourceId: careerSourceId },
    });
  } else if (
    ["ANALYSIS_COMPLETED", "ANALYSIS_INPUT_REQUIRED"].includes(item.type) &&
    postingId
  ) {
    await router.push({
      name: "posting-detail",
      params: { postingId },
    });
  } else if (item.type === "ANALYSIS_COMPLETED" && analysisJobId) {
    await router.push({ name: "chat", query: { analysisJobId } });
  } else if (item.type === "CAREER_MAP_UPDATED" || item.type === "EVIDENCE_VERIFIED") {
    await router.push({ name: "map" });
  } else {
    await router.push({ name: "activity" });
  }
}

async function readAll() {
  await api.readAllNotifications();
  notifications.value = notifications.value.map((item) => ({
    ...item,
    readAt: item.readAt ?? new Date().toISOString(),
  }));
  unreadCount.value = 0;
}

async function newConversation() {
  showNotifications.value = false;
  await router.push({ name: "chat", query: { new: Date.now().toString() } });
}

async function logout() {
  headerError.value = "";
  try {
    await api.logout();
    session.clear();
    await router.push({ name: "login" });
  } catch (cause) {
    headerError.value = cause instanceof Error ? cause.message : "로그아웃하지 못했습니다.";
  }
}

function handleUnauthorized() {
  session.clear();
  void router.push({ name: "login", query: { expired: "1" } });
}

onMounted(() => {
  window.addEventListener("jobiss:unauthorized", handleUnauthorized);
  void loadNotifications();
  notificationTimer = window.setInterval(loadNotifications, 15000);
});

onBeforeUnmount(() => {
  window.removeEventListener("jobiss:unauthorized", handleUnauthorized);
  if (notificationTimer) window.clearInterval(notificationTimer);
});
</script>

<template>
  <div class="app-shell" :class="{ 'app-shell--sidebar-collapsed': sidebarCollapsed }">
    <aside class="app-sidebar">
      <RouterLink class="brand app-sidebar__brand" :to="{ name: 'home' }">
        <span class="brand-mark">J</span>
        <span class="sidebar-label">J.O.B.I.S</span>
      </RouterLink>
      <button
        class="sidebar-toggle"
        type="button"
        :aria-label="sidebarCollapsed ? '메뉴 펼치기' : '메뉴 접기'"
        :title="sidebarCollapsed ? '메뉴 펼치기' : '메뉴 접기'"
        @click="toggleSidebar"
      >
        <PanelLeftOpen v-if="sidebarCollapsed" :size="20" />
        <PanelLeftClose v-else :size="20" />
      </button>

      <nav class="main-nav app-sidebar__nav" aria-label="주요 메뉴">
        <RouterLink
          :class="{ 'nav-section-active': sectionActive('/app') }"
          :to="{ name: 'home' }"
        >
          <House :size="19" />
          <span class="sidebar-label">홈</span>
        </RouterLink>
        <RouterLink
          :class="{ 'nav-section-active': sectionActive('/app/chat') }"
          :to="{ name: 'chat' }"
        >
          <MessageCircle :size="19" />
          <span class="sidebar-label">대화</span>
        </RouterLink>
        <RouterLink
          :class="{ 'nav-section-active': sectionActive('/app/storage') }"
          :to="{ name: 'storage' }"
        >
          <Archive :size="19" />
          <span class="sidebar-label">커리어 저장소</span>
        </RouterLink>
        <RouterLink
          :class="{ 'nav-section-active': sectionActive('/app/postings') }"
          :to="{ name: 'postings' }"
        >
          <BriefcaseBusiness :size="19" />
          <span class="sidebar-label">채용 공고</span>
        </RouterLink>
        <RouterLink
          :class="{ 'nav-section-active': sectionActive('/app/map') }"
          :to="{ name: 'map' }"
        >
          <Map :size="19" />
          <span class="sidebar-label">커리어 지도</span>
        </RouterLink>
        <RouterLink
          :class="{ 'nav-section-active': sectionActive('/app/map-2') }"
          :to="{ name: 'map-2' }"
        >
          <Orbit :size="19" />
          <span class="sidebar-label">커리어 지도 2</span>
        </RouterLink>
        <RouterLink
          :class="{ 'nav-section-active': sectionActive('/app/activity') }"
          :to="{ name: 'activity' }"
        >
          <Activity :size="19" />
          <span class="sidebar-label">활동 내역</span>
          <b v-if="unreadCount" class="nav-count">{{ unreadCount > 99 ? "99+" : unreadCount }}</b>
        </RouterLink>
      </nav>

      <button
        class="press-button press-button--primary app-sidebar__new"
        type="button"
        @click="newConversation"
      >
        <Plus :size="18" :stroke-width="3" />
        <span class="sidebar-label">새 대화</span>
      </button>

      <div class="app-sidebar__account">
        <RouterLink :to="{ name: 'settings' }" class="sidebar-profile">
          <span class="profile-button">{{ initial }}</span>
          <span class="sidebar-label">
            <strong>{{ session.user.value?.displayName }}</strong>
            <small>{{ session.user.value?.email }}</small>
          </span>
          <Settings class="sidebar-label" :size="17" />
        </RouterLink>
        <button class="icon-button" type="button" aria-label="로그아웃" @click="logout">
          <LogOut :size="19" />
        </button>
      </div>
    </aside>

    <header class="app-header app-topbar">
      <RouterLink class="brand app-topbar__brand" :to="{ name: 'home' }">
        <span class="brand-mark">J</span>
        <span>J.O.B.I.S</span>
      </RouterLink>
      <span class="app-topbar__status">
        <i />
        AI 작업은 다른 화면에서도 계속됩니다
      </span>
      <div class="header-actions">
        <div class="notification-wrap">
          <button
            class="icon-button notification-button"
            type="button"
            aria-label="알림"
            :aria-expanded="showNotifications"
            @click="showNotifications = !showNotifications"
          >
            <Bell :size="19" />
            <b v-if="unreadCount">{{ unreadCount > 99 ? "99+" : unreadCount }}</b>
          </button>
          <section v-if="showNotifications" class="notification-popover">
            <header>
              <div>
                <p class="eyebrow">NOTIFICATIONS</p>
                <h2>알림</h2>
              </div>
              <button v-if="unreadCount" class="text-action" type="button" @click="readAll">
                <Check :size="14" /> 모두 읽음
              </button>
            </header>
            <div v-if="notifications.length" class="notification-list">
              <button
                v-for="item in notifications"
                :key="item.id"
                type="button"
                :class="{ unread: !item.readAt }"
                @click="openNotification(item)"
              >
                <i />
                <span>
                  <strong>{{ item.title }}</strong>
                  <p>{{ item.body }}</p>
                  <small>{{ formatTime(item.createdAt) }}</small>
                </span>
              </button>
            </div>
            <p v-else class="notification-empty">새 알림이 없습니다.</p>
            <RouterLink
              class="notification-all"
              :to="{ name: 'activity' }"
              @click="showNotifications = false"
            >
              전체 활동 내역
            </RouterLink>
          </section>
        </div>
        <RouterLink class="profile-button app-topbar__profile" :to="{ name: 'settings' }">
          {{ initial }}
        </RouterLink>
      </div>
    </header>
    <p v-if="headerError" class="header-error">{{ headerError }}</p>

    <div class="app-route">
      <RouterView />
    </div>
  </div>
</template>
