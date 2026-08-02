import { createRouter, createWebHistory } from "vue-router";

import { session } from "@/session";
import AppShell from "@/components/AppShell.vue";
import ActivityView from "@/views/ActivityView.vue";
import CareerMapView from "@/views/CareerMapView.vue";
import CareerMapVerticalView from "@/views/CareerMapVerticalView.vue";
import CareerSourceReviewView from "@/views/CareerSourceReviewView.vue";
import ChatView from "@/views/ChatView.vue";
import HomeView from "@/views/HomeView.vue";
import LoginView from "@/views/LoginView.vue";
import LandingView from "@/views/LandingView.vue";
import NewPostingView from "@/views/NewPostingView.vue";
import PostingDetailView from "@/views/PostingDetailView.vue";
import PostingsView from "@/views/PostingsView.vue";
import RoadmapPrototypeView from "@/views/RoadmapPrototypeView.vue";
import SettingsView from "@/views/SettingsView.vue";
import StorageView from "@/views/StorageView.vue";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      name: "landing",
      component: LandingView,
      meta: { public: true },
    },
    {
      path: "/login",
      name: "login",
      component: LoginView,
      meta: { public: true },
    },
    {
      path: "/roadmap-preview",
      name: "roadmap-preview",
      component: RoadmapPrototypeView,
      meta: { public: true },
    },
    {
      path: "/app",
      component: AppShell,
      children: [
        { path: "", name: "home", component: HomeView },
        { path: "chat", name: "chat", component: ChatView },
        { path: "storage", name: "storage", component: StorageView },
        {
          path: "storage/sources/:sourceId",
          name: "career-source-review",
          component: CareerSourceReviewView,
        },
        { path: "postings", name: "postings", component: PostingsView },
        { path: "postings/new", name: "posting-new", component: NewPostingView },
        {
          path: "postings/:postingId",
          name: "posting-detail",
          component: PostingDetailView,
        },
        { path: "map", name: "map", component: CareerMapView },
        { path: "map-2", name: "map-2", component: CareerMapVerticalView },
        { path: "activity", name: "activity", component: ActivityView },
        { path: "settings", name: "settings", component: SettingsView },
      ],
    },
  ],
});

router.beforeEach(async (to) => {
  await session.restore();
  if (!to.meta.public && !session.authenticated.value) {
    return { name: "login", query: { redirect: to.fullPath } };
  }
  if (to.name === "login" && session.authenticated.value) {
    return { name: "home" };
  }
  return true;
});
