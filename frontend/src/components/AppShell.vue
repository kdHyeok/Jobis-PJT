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
  Plus,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  ClipboardCheck,
} from "@lucide/vue";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { RouterLink, RouterView, useRoute, useRouter } from "vue-router";

import { api } from "@/api";
import { notificationDestination } from "@/notification-routing";
import { session } from "@/session";
import type { ActivityJob, NotificationItem } from "@/types";

const router = useRouter();
const route = useRoute();
const initial = computed(() => session.user.value?.displayName.slice(0, 1) ?? "J");
const notifications = ref<NotificationItem[]>([]);
const activeJobs = ref<ActivityJob[]>([]);
const unreadCount = ref(0);
const showNotifications = ref(false);
const sidebarCollapsed = ref(
  window.localStorage.getItem("jobiss:sidebar-collapsed") === "1",
);
const headerError = ref("");
const notificationError = ref("");
const notificationWrap = ref<HTMLElement | null>(null);
let notificationTimer: number | null = null;

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
    notificationError.value = "";
  } catch (cause) {
    if (showNotifications.value) {
      notificationError.value = cause instanceof Error ? cause.message : "알림을 불러오지 못했습니다.";
    }
  }
}

async function loadActiveJobs() {
  try {
    activeJobs.value = await api.activityJobs();
  } catch {
    // 전역 상태 표시는 보조 정보다. 개별 화면의 오류 처리를 가리지 않는다.
  }
}

async function openNotification(item: NotificationItem) {
  notificationError.value = "";
  try {
    if (!item.readAt) {
      await api.readNotification(item.id);
      item.readAt = new Date().toISOString();
      unreadCount.value = Math.max(0, unreadCount.value - 1);
    }
    showNotifications.value = false;
    await router.push(notificationDestination(item));
  } catch (cause) {
    notificationError.value = cause instanceof Error ? cause.message : "알림을 열지 못했습니다.";
  }
}

async function readAll() {
  notificationError.value = "";
  try {
    await api.readAllNotifications();
    notifications.value = notifications.value.map((item) => ({
      ...item,
      readAt: item.readAt ?? new Date().toISOString(),
    }));
    unreadCount.value = 0;
  } catch (cause) {
    notificationError.value = cause instanceof Error ? cause.message : "알림을 읽음 처리하지 못했습니다.";
  }
}

function handleDocumentPointer(event: PointerEvent) {
  if (showNotifications.value && !notificationWrap.value?.contains(event.target as Node)) {
    showNotifications.value = false;
  }
}

function handleDocumentKeydown(event: KeyboardEvent) {
  if (event.key === "Escape") showNotifications.value = false;
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

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value;
  window.localStorage.setItem(
    "jobiss:sidebar-collapsed",
    sidebarCollapsed.value ? "1" : "0",
  );
}

function handleUnauthorized() {
  session.clear();
  void router.push({ name: "login", query: { expired: "1" } });
}

onMounted(() => {
  document.body.classList.add("app-body-locked");
  window.addEventListener("jobiss:unauthorized", handleUnauthorized);
  document.addEventListener("pointerdown", handleDocumentPointer);
  document.addEventListener("keydown", handleDocumentKeydown);
  void loadNotifications();
  void loadActiveJobs();
  notificationTimer = window.setInterval(() => {
    void loadNotifications();
    void loadActiveJobs();
  }, 5000);
});

onBeforeUnmount(() => {
  document.body.classList.remove("app-body-locked");
  window.removeEventListener("jobiss:unauthorized", handleUnauthorized);
  document.removeEventListener("pointerdown", handleDocumentPointer);
  document.removeEventListener("keydown", handleDocumentKeydown);
  if (notificationTimer) window.clearInterval(notificationTimer);
});
</script>

<template>
  <div
    class="app-shell"
    :class="{ 'app-shell--sidebar-collapsed': sidebarCollapsed }"
  >
    <aside class="app-sidebar">
      <div class="app-sidebar__top">
        <RouterLink class="brand app-sidebar__brand" :to="{ name: 'home' }">
          <span class="brand-mark">J</span>
          <span class="sidebar-label">JOBIS</span>
        </RouterLink>
        <button
          class="sidebar-collapse-button"
          type="button"
          :aria-label="sidebarCollapsed ? '사이드바 펼치기' : '사이드바 접기'"
          :title="sidebarCollapsed ? '사이드바 펼치기' : '사이드바 접기'"
          @click="toggleSidebar"
        >
          <PanelLeftOpen v-if="sidebarCollapsed" :size="18" />
          <PanelLeftClose v-else :size="18" />
        </button>
      </div>

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
          :class="{ 'nav-section-active': sectionActive('/app/activity') }"
          :to="{ name: 'activity' }"
        >
          <Activity :size="19" />
          <span class="sidebar-label">활동 내역</span>
          <b v-if="unreadCount" class="nav-count">{{ unreadCount > 99 ? "99+" : unreadCount }}</b>
        </RouterLink>
        <RouterLink
          v-if="session.user.value?.accountRole === 'OPERATOR'"
          :class="{ 'nav-section-active': sectionActive('/app/operator') }"
          :to="{ name: 'operator' }"
        >
          <ClipboardCheck :size="19" />
          <span class="sidebar-label">운영 검토함</span>
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
          <span class="sidebar-account-copy">
            <strong>{{ session.user.value?.displayName }}</strong>
            <small>{{ session.user.value?.email }}</small>
          </span>
          <Settings :size="17" />
        </RouterLink>
        <button class="icon-button" type="button" aria-label="로그아웃" @click="logout">
          <LogOut :size="19" />
        </button>
      </div>
    </aside>

    <header class="app-header app-topbar">
      <RouterLink class="brand app-topbar__brand" :to="{ name: 'home' }">
        <span class="brand-mark">J</span>
        <span>JOBIS</span>
      </RouterLink>
      <RouterLink v-if="activeJobs.length" class="app-topbar__status" :to="{ name: 'activity' }">
        <i />
        JOBIS 작업 {{ activeJobs.length }}개 진행 중
      </RouterLink>
      <div class="header-actions">
        <div ref="notificationWrap" class="notification-wrap">
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
          <section v-if="showNotifications" class="notification-popover" aria-label="알림 목록">
            <header>
              <div>
                <p class="eyebrow">NOTIFICATIONS</p>
                <h2>알림</h2>
              </div>
              <button v-if="unreadCount" class="text-action" type="button" @click="readAll">
                <Check :size="14" /> 모두 읽음
              </button>
            </header>
            <p v-if="notificationError" class="inline-error" role="alert">{{ notificationError }}</p>
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
    <p v-if="headerError" class="header-error" role="alert">{{ headerError }}</p>

    <div
      class="app-route"
      :class="{ 'app-route--chat': route.name === 'chat' }"
    >
      <RouterView />
    </div>
  </div>
</template>
