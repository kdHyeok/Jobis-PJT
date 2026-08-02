<script setup lang="ts">
import { ArrowRight, Check, GitBranch, Sparkles } from "@lucide/vue";
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api } from "@/api";
import JobissGuide from "@/components/JobissGuide.vue";
import { session } from "@/session";

const mode = ref<"login" | "register">("login");
const email = ref("");
const password = ref("");
const displayName = ref("");
const busy = ref(false);
const error = ref("");
const route = useRoute();
const router = useRouter();
if (route.query.expired === "1") {
  error.value = "로그인 시간이 만료되었습니다. 다시 로그인해 주세요.";
}

const title = computed(() =>
  mode.value === "login" ? "다시 이어서 가볼까요?" : "나만의 커리어 지도를 시작해요",
);

async function submit() {
  busy.value = true;
  error.value = "";
  try {
    const user =
      mode.value === "login"
        ? await api.login(email.value, password.value)
        : await api.register(email.value, password.value, displayName.value);
    session.setUser(user);
    const redirect =
      typeof route.query.redirect === "string" ? route.query.redirect : "/app";
    await router.push(redirect);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "로그인하지 못했습니다.";
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <main class="login-page">
    <section class="login-story">
      <a class="brand brand--large" href="/">
        <span class="brand-mark">J</span>
        <span>J.O.B.I.S</span>
      </a>
      <div class="login-copy">
        <p class="eyebrow">ONE CAREER, MANY DESTINATIONS</p>
        <h1>공고를 모을수록<br />당신의 다음 길이 선명해집니다.</h1>
        <p>
          회사마다 로드맵을 다시 만드는 대신, 이미 쌓은 경험 위에 새로운 기회를
          연결합니다.
        </p>
      </div>
      <div class="login-path" aria-hidden="true">
        <span class="mini-node mini-node--done"><Check :size="20" /></span>
        <i />
        <span class="mini-node mini-node--current"><GitBranch :size="21" /></span>
        <i />
        <span class="mini-node mini-node--goal"><Sparkles :size="21" /></span>
      </div>
      <JobissGuide message="첫 로그인에는 공통 기반 세 단계만 준비해 둘게요." />
    </section>

    <section class="login-panel">
      <form class="auth-card" @submit.prevent="submit">
        <div>
          <p class="eyebrow">{{ mode === "login" ? "WELCOME BACK" : "START JOURNEY" }}</p>
          <h2>{{ title }}</h2>
          <p>목업 계정 없이 실제 사용자 데이터로 시작합니다.</p>
        </div>

        <label v-if="mode === 'register'">
          이름
          <input v-model="displayName" autocomplete="name" required maxlength="80" />
        </label>
        <label>
          이메일
          <input v-model="email" type="email" autocomplete="email" required />
        </label>
        <label>
          비밀번호
          <input
            v-model="password"
            type="password"
            :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"
            :minlength="mode === 'register' ? 12 : undefined"
            maxlength="100"
            required
          />
          <small v-if="mode === 'register'">12자 이상, 다른 서비스와 겹치지 않는 비밀번호를 사용하세요.</small>
        </label>

        <p v-if="error" class="form-error" role="alert">{{ error }}</p>

        <button class="press-button press-button--primary auth-submit" :disabled="busy">
          {{ busy ? "확인 중…" : mode === "login" ? "로그인" : "계정 만들기" }}
          <ArrowRight :size="18" />
        </button>

        <button
          class="text-button"
          type="button"
          @click="mode = mode === 'login' ? 'register' : 'login'"
        >
          {{
            mode === "login"
              ? "처음인가요? 계정 만들기"
              : "이미 계정이 있나요? 로그인"
          }}
        </button>
      </form>
    </section>
  </main>
</template>
