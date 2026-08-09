import { createRouter, createWebHistory } from "vue-router";

import { session } from "@/session";
import AppShell from "@/components/AppShell.vue";
import ActivityView from "@/views/ActivityView.vue";
import CareerMapView from "@/views/CareerMapView.vue";
import CareerSourceReviewView from "@/views/CareerSourceReviewView.vue";
import ChatView from "@/views/ChatView.vue";
import HomeView from "@/views/HomeView.vue";
import PasswordResetRequestView from "@/views/PasswordResetRequestView.vue";
import PasswordResetView from "@/views/PasswordResetView.vue";
import PolicyView from "@/views/PolicyView.vue";
import LandingView from "@/views/LandingView.vue";
import NewPostingView from "@/views/NewPostingView.vue";
import PostingDetailView from "@/views/PostingDetailView.vue";
import PostingsView from "@/views/PostingsView.vue";
import SettingsView from "@/views/SettingsView.vue";
import OperatorView from "@/views/OperatorView.vue";
import StorageView from "@/views/StorageView.vue";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      name: "landing",
      component: LandingView,
      meta: { public: true, title: "커리어 지도" },
    },
    {
      path: "/login",
      name: "login",
      redirect: (to) => {
        const { mode, ...query } = to.query;
        return {
          name: "landing",
          query: {
            ...query,
            auth: mode === "register" ? "register" : "login",
          },
        };
      },
      meta: { public: true, title: "로그인" },
    },
    { path: "/forgot-password", name: "forgot-password", component: PasswordResetRequestView, meta: { public: true, title: "비밀번호 재설정" } },
    { path: "/reset-password", name: "reset-password", component: PasswordResetView, meta: { public: true, title: "새 비밀번호 설정" } },
    { path: "/terms", name: "terms", component: PolicyView, meta: { public: true, title: "이용약관" } },
    { path: "/privacy", name: "privacy", component: PolicyView, meta: { public: true, title: "개인정보 처리 안내" } },
    {
      path: "/app",
      component: AppShell,
      children: [
        { path: "", name: "home", component: HomeView, meta: { title: "홈" } },
        { path: "chat", name: "chat", component: ChatView, meta: { title: "AI 대화" } },
        { path: "storage", name: "storage", component: StorageView, meta: { title: "커리어 저장소" } },
        {
          path: "storage/sources/:sourceId",
          name: "career-source-review",
          component: CareerSourceReviewView,
          meta: { title: "자료 검토" },
        },
        { path: "postings", name: "postings", component: PostingsView, meta: { title: "채용 공고" } },
        { path: "postings/new", name: "posting-new", component: NewPostingView, meta: { title: "새 공고 분석" } },
        {
          path: "postings/:postingId",
          name: "posting-detail",
          component: PostingDetailView,
          meta: { title: "공고 분석" },
        },
        { path: "map", name: "map", component: CareerMapView, meta: { title: "커리어 지도" } },
        { path: "map/v3", name: "map-v3", redirect: { name: "map" } },
        { path: "activity", name: "activity", component: ActivityView, meta: { title: "활동 내역" } },
        { path: "settings", name: "settings", component: SettingsView, meta: { title: "설정" } },
        {
          path: "operator",
          name: "operator",
          component: OperatorView,
          meta: { operator: true, title: "운영 검토함" },
        },
      ],
    },
  ],
});

router.afterEach(() => {
  document.title = "JOBIS";
});

router.beforeEach(async (to) => {
  await session.restore();
  if (!to.meta.public && !session.authenticated.value) {
    return { name: "login", query: { redirect: to.fullPath } };
  }
  if (to.name === "login" && session.authenticated.value) {
    return { name: "home" };
  }
  if (to.meta.operator && session.user.value?.accountRole !== "OPERATOR") {
    return { name: "home" };
  }
  return true;
});
