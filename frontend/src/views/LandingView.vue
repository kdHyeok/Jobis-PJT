<script setup lang="ts">
import { GitBranch, MessageCircle, ShieldCheck } from "@lucide/vue";
import { ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import logoWordmark from "@/assets/logo-wordmark.png";
import AuthModal from "@/components/AuthModal.vue";
import InkBackground from "@/components/InkBackground.vue";

type AuthMode = "login" | "register";

const route = useRoute();
const router = useRouter();
function routeAuthMode(): AuthMode | null {
  if (route.query.auth === "register") return "register";
  if (route.query.auth === "login") return "login";
  return null;
}

const authMode = ref<AuthMode | null>(routeAuthMode());

watch(
  () => route.query.auth,
  () => {
    authMode.value = routeAuthMode();
  },
);

function setAuthMode(mode: AuthMode) {
  authMode.value = mode;
  void router.push({
    name: "landing",
    query: { ...route.query, auth: mode },
  });
}

function closeAuthModal() {
  authMode.value = null;
  const query = { ...route.query };
  delete query.auth;
  void router.replace({ name: "landing", query });
}
</script>

<template>
  <main class="landing-page public-shell">
    <InkBackground />

    <header class="landing-auth-nav" aria-label="계정 메뉴">
      <button
        class="press-button press-button--ghost"
        type="button"
        @click="setAuthMode('login')"
      >
        로그인
      </button>
      <button
        class="press-button press-button--primary"
        type="button"
        @click="setAuthMode('register')"
      >
        회원가입
      </button>
    </header>

    <section class="landing-hero">
      <img
        class="landing-logo"
        :src="logoWordmark"
        alt="JOBISS"
        draggable="false"
      />
      <p class="landing-tagline">AI가 찾아주는 나에게 맞는 일자리</p>
      <p class="landing-lead">
        AI와 대화하며 목표를 찾고, 공고를 분석하고, 실제 증거로 단계를 완료하세요.
      </p>
    </section>

    <section id="how" class="landing-features">
      <article>
        <MessageCircle :size="28" />
        <h2>대화로 시작</h2>
        <p>공고가 없어도 현재 상황과 목표부터 자유롭게 이야기합니다.</p>
      </article>
      <article>
        <GitBranch :size="28" />
        <h2>하나의 누적 지도</h2>
        <p>여러 회사의 공통 경로와 갈라지는 조건을 한눈에 비교합니다.</p>
      </article>
      <article>
        <ShieldCheck :size="28" />
        <h2>증거로 완료</h2>
        <p>전문 단계는 코드·프로젝트·자격 증거를 검증한 뒤 완료됩니다.</p>
      </article>
    </section>

    <AuthModal
      v-if="authMode"
      :mode="authMode"
      @close="closeAuthModal"
      @mode-change="setAuthMode"
    />
  </main>
</template>
