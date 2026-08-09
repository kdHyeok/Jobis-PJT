<script setup lang="ts">
import {
  Activity,
  Archive,
  BriefcaseBusiness,
  ClipboardCheck,
  LoaderCircle,
  LogOut,
  Map,
  MessageCircle,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Search,
  Settings,
  X,
} from "@lucide/vue";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { RouterLink, RouterView, useRoute, useRouter } from "vue-router";

import { api } from "@/api";
import logoMark from "@/assets/logo-mark.png";
import logoWordmark from "@/assets/logo-wordmark.png";
import ConversationShelf from "@/components/ConversationShelf.vue";
import { productDialog } from "@/product-dialog";
import { session } from "@/session";
import type { ActivityJob } from "@/types";

const router = useRouter();
const route = useRoute();
const initial = computed(() => session.user.value?.displayName.slice(0, 1) ?? "J");
const activeJobs = ref<ActivityJob[]>([]);
const activeJobEstimate = computed(() => {
  const remaining = activeJobs.value
    .map((job) => job.estimatedRemainingSeconds)
    .filter((seconds): seconds is number => seconds !== null && Number.isFinite(seconds));
  if (remaining.length === 0) return "예상 시간 계산 중";
  const seconds = Math.max(...remaining);
  if (seconds <= 60) return "1분 이내";
  return `약 ${Math.ceil(seconds / 60)}분 남음`;
});
const unreadCount = ref(0);
const showUserMenu = ref(false);
const showConversationSearch = ref(false);
const conversationSearchQuery = ref("");
const sidebarCollapsed = ref(
  window.localStorage.getItem("jobiss:sidebar-collapsed") === "1",
);
const headerError = ref("");
const accountWrap = ref<HTMLElement | null>(null);
const conversationSearchWrap = ref<HTMLElement | null>(null);
let refreshTimer: number | null = null;

function sectionActive(section: string) {
  if (section === "/app") return route.path === section;
  return route.path === section || route.path.startsWith(`${section}/`);
}

async function loadGlobalStatus() {
  const [notificationResult, activityResult] = await Promise.allSettled([
    api.notifications(),
    api.activityJobs(),
  ]);
  if (notificationResult.status === "fulfilled") {
    unreadCount.value = notificationResult.value.unreadCount;
  }
  if (activityResult.status === "fulfilled") {
    activeJobs.value = activityResult.value;
  }
}

function handleDocumentPointer(event: PointerEvent) {
  if (showUserMenu.value && !accountWrap.value?.contains(event.target as Node)) {
    showUserMenu.value = false;
  }
  if (
    showConversationSearch.value &&
    !conversationSearchWrap.value?.contains(event.target as Node)
  ) {
    showConversationSearch.value = false;
  }
}

function handleDocumentKeydown(event: KeyboardEvent) {
  if (event.key === "Escape") {
    showUserMenu.value = false;
    showConversationSearch.value = false;
  }
}

function submitConversationSearch() {
  window.dispatchEvent(new CustomEvent("jobiss:conversation-search", {
    detail: { query: conversationSearchQuery.value.trim() },
  }));
  showConversationSearch.value = false;
}

function clearConversationSearch() {
  conversationSearchQuery.value = "";
  submitConversationSearch();
}

async function logout() {
  const confirmed = await productDialog.confirm({
    title: "로그아웃",
    message: "정말로 로그아웃하시겠습니까?",
    confirmLabel: "예, 로그아웃",
    cancelLabel: "아니요",
    danger: true,
  });
  if (!confirmed) return;

  headerError.value = "";
  try {
    await api.logout();
    session.clear();
    await router.push({ name: "landing" });
  } catch (cause) {
    headerError.value = cause instanceof Error ? cause.message : "로그아웃하지 못했습니다.";
  }
}

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value;
  showUserMenu.value = false;
  showConversationSearch.value = false;
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
  void loadGlobalStatus();
  refreshTimer = window.setInterval(() => void loadGlobalStatus(), 5000);
});

onBeforeUnmount(() => {
  document.body.classList.remove("app-body-locked");
  window.removeEventListener("jobiss:unauthorized", handleUnauthorized);
  document.removeEventListener("pointerdown", handleDocumentPointer);
  document.removeEventListener("keydown", handleDocumentKeydown);
  if (refreshTimer) window.clearInterval(refreshTimer);
});
</script>

<template>
  <div
    class="app-shell"
    :class="{
      'app-shell--sidebar-collapsed': sidebarCollapsed,
      'app-shell--chat': route.name === 'chat',
    }"
  >
    <aside class="app-sidebar">
      <div class="app-sidebar__top">
        <RouterLink class="brand app-sidebar__brand" :to="{ name: 'home' }">
          <img
            v-if="sidebarCollapsed"
            class="brand-mark-logo"
            :src="logoMark"
            alt="JOBISS"
            draggable="false"
          />
          <img
            v-else
            class="brand-logo"
            :src="logoWordmark"
            alt="JOBISS"
            draggable="false"
          />
        </RouterLink>
        <div ref="conversationSearchWrap" class="sidebar-conversation-search">
          <button
            class="sidebar-conversation-search__trigger"
            type="button"
            aria-label="대화 검색"
            :aria-expanded="showConversationSearch"
            title="대화 검색"
            @click="showConversationSearch = !showConversationSearch"
          >
            <Search :size="18" />
          </button>
          <form
            v-if="showConversationSearch"
            class="sidebar-conversation-search__panel"
            role="search"
            @submit.prevent="submitConversationSearch"
          >
            <label for="global-conversation-search">대화 검색</label>
            <div>
              <Search :size="16" />
              <input
                id="global-conversation-search"
                v-model="conversationSearchQuery"
                autofocus
                type="search"
                placeholder="제목이나 대화 내용 검색"
              />
              <button
                v-if="conversationSearchQuery"
                type="button"
                aria-label="검색어 지우기"
                @click="clearConversationSearch"
              >
                <X :size="15" />
              </button>
            </div>
            <button class="press-button press-button--primary" type="submit">검색</button>
          </form>
        </div>
      </div>

      <nav class="main-nav app-sidebar__nav" aria-label="주요 메뉴">
        <RouterLink class="new-chat-nav" :to="{ name: 'home', query: { focus: 'chat' } }">
          <span class="new-chat-nav__icon" aria-hidden="true">
            <MessageCircle :size="20" />
            <Plus :size="11" :stroke-width="3" />
          </span>
          <span class="sidebar-label">새 대화</span>
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
          v-if="session.user.value?.accountRole === 'OPERATOR'"
          :class="{ 'nav-section-active': sectionActive('/app/operator') }"
          :to="{ name: 'operator' }"
        >
          <ClipboardCheck :size="19" />
          <span class="sidebar-label">운영 검토함</span>
        </RouterLink>
      </nav>

      <div id="sidebar-conversations" class="app-sidebar__conversations">
        <ConversationShelf v-if="route.name !== 'chat'" />
      </div>

      <div ref="accountWrap" class="app-sidebar__account">
        <button
          class="sidebar-profile"
          type="button"
          :aria-expanded="showUserMenu"
          aria-haspopup="menu"
          @click="showUserMenu = !showUserMenu"
        >
          <span class="profile-button sidebar-profile__avatar">{{ initial }}</span>
          <b v-if="unreadCount" class="sidebar-profile__badge">
            {{ unreadCount > 99 ? "99+" : unreadCount }}
          </b>
          <span class="sidebar-account-copy">
            <strong>{{ session.user.value?.displayName }}</strong>
            <small>{{ session.user.value?.email }}</small>
          </span>
        </button>

        <section v-if="showUserMenu" class="sidebar-user-menu" role="menu">
          <header>
            <span class="profile-button">{{ initial }}</span>
            <span>
              <strong>{{ session.user.value?.displayName }}</strong>
              <small>{{ session.user.value?.email }}</small>
            </span>
          </header>
          <RouterLink role="menuitem" :to="{ name: 'activity' }" @click="showUserMenu = false">
            <Activity :size="18" />
            <span>활동 내역</span>
            <b v-if="unreadCount">{{ unreadCount > 99 ? "99+" : unreadCount }}</b>
          </RouterLink>
          <RouterLink role="menuitem" :to="{ name: 'settings' }" @click="showUserMenu = false">
            <Settings :size="18" />
            <span>설정</span>
          </RouterLink>
          <button role="menuitem" type="button" @click="logout">
            <LogOut :size="18" />
            <span>로그아웃</span>
          </button>
        </section>
      </div>
    </aside>

    <header class="app-header app-topbar">
      <button
        class="sidebar-collapse-button sidebar-collapse-button--topbar"
        type="button"
        :aria-label="sidebarCollapsed ? '사이드바 펼치기' : '사이드바 접기'"
        :title="sidebarCollapsed ? '사이드바 펼치기' : '사이드바 접기'"
        @click="toggleSidebar"
      >
        <PanelLeftOpen v-if="sidebarCollapsed" :size="18" />
        <PanelLeftClose v-else :size="18" />
      </button>
      <RouterLink class="brand app-topbar__brand" :to="{ name: 'home' }">
        <img class="brand-logo" :src="logoWordmark" alt="JOBISS" draggable="false" />
      </RouterLink>
      <div id="app-topbar-center" class="app-topbar__center" />
      <div class="app-topbar__right">
        <RouterLink v-if="activeJobs.length" class="app-topbar__status" :to="{ name: 'activity' }">
          <LoaderCircle class="spin app-topbar__status-spinner" :size="15" />
          <span>
            JOBIS 작업 {{ activeJobs.length }}개 진행 중
            <small>{{ activeJobEstimate }}</small>
          </span>
        </RouterLink>
        <div id="app-topbar-actions" class="app-topbar__actions" />
      </div>
    </header>
    <p v-if="headerError" class="header-error" role="alert">{{ headerError }}</p>

    <div class="app-route" :class="{ 'app-route--chat': route.name === 'chat' }">
      <RouterView />
    </div>
  </div>
</template>
