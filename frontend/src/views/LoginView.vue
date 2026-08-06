<script setup lang="ts">
import { ArrowRight, Check, Eye, EyeOff, GitBranch, Sparkles } from "@lucide/vue";
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api } from "@/api";
import JobissGuide from "@/components/JobissGuide.vue";
import { session } from "@/session";

const mode = ref<"login" | "register">("login");
const email = ref("");
const password = ref("");
const passwordConfirm = ref("");
const showPassword = ref(false);
const acceptedTerms = ref(false);
const rememberMe = ref(false);
const displayName = ref("");
const busy = ref(false);
const error = ref("");
const route = useRoute();
const router = useRouter();
if (route.query.expired === "1") {
  error.value = "로그인 시간이 만료되었습니다. 다시 로그인해 주세요.";
}
const notice = ref(
  route.query.passwordChanged === "1"
    ? "비밀번호가 변경되었습니다. 새 비밀번호로 다시 로그인해 주세요."
    : route.query.reset === "1"
      ? "비밀번호를 재설정했습니다. 새 비밀번호로 로그인해 주세요."
      : "",
);

const title = computed(() =>
  mode.value === "login" ? "다시 이어서 가볼까요?" : "나만의 커리어 지도를 시작해요",
);

async function submit() {
  if (mode.value === "register" && password.value !== passwordConfirm.value) {
    error.value = "비밀번호 확인이 일치하지 않습니다.";
    return;
  }
  if (mode.value === "register" && !acceptedTerms.value) {
    error.value = "이용약관과 개인정보 처리 안내에 동의해 주세요.";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    const user =
      mode.value === "login"
        ? await api.login(email.value, password.value, rememberMe.value)
        : await api.register(email.value, password.value, displayName.value);
    session.setUser(user);
    const requestedRedirect =
      typeof route.query.redirect === "string" ? route.query.redirect : "";
    const redirect =
      requestedRedirect.startsWith("/app") && !requestedRedirect.startsWith("//")
        ? requestedRedirect
        : "/app";
    await router.push(redirect);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "로그인하지 못했습니다.";
  } finally {
    busy.value = false;
  }
}

function switchMode() {
  mode.value = mode.value === "login" ? "register" : "login";
  error.value = "";
  password.value = "";
  passwordConfirm.value = "";
  acceptedTerms.value = false;
}
</script>

<template>
  <main class="login-page">
    <section class="login-story">
      <a class="brand brand--large" href="/">
        <span class="brand-mark">J</span>
        <span>JOBIS</span>
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
        <RouterLink class="login-mobile-brand brand" to="/">
          <span class="brand-mark">J</span><span>JOBIS</span>
        </RouterLink>
        <div>
          <p class="eyebrow">{{ mode === "login" ? "WELCOME BACK" : "START JOURNEY" }}</p>
          <h2>{{ title }}</h2>
          <p>공고와 경험을 안전하게 저장하고 어디서든 이어서 준비하세요.</p>
        </div>

        <label v-if="mode === 'register'">
          이름
          <input v-model="displayName" autocomplete="name" required maxlength="80" />
        </label>
        <label>
          이메일
          <input v-model="email" type="email" autocomplete="email" required />
        </label>
        <label class="password-field">
          비밀번호
          <span>
            <input
              v-model="password"
              :type="showPassword ? 'text' : 'password'"
              :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"
              :minlength="mode === 'register' ? 12 : undefined"
              maxlength="100"
              required
            />
            <button type="button" :aria-label="showPassword ? '비밀번호 숨기기' : '비밀번호 보기'" @click="showPassword = !showPassword">
              <EyeOff v-if="showPassword" :size="17" /><Eye v-else :size="17" />
            </button>
          </span>
          <small v-if="mode === 'register'">12자 이상, 다른 서비스와 겹치지 않는 비밀번호를 사용하세요.</small>
        </label>
        <RouterLink v-if="mode === 'login'" class="auth-forgot-link" to="/forgot-password">
          비밀번호를 잊으셨나요?
        </RouterLink>
        <label v-if="mode === 'login'" class="auth-consent auth-remember">
          <input v-model="rememberMe" type="checkbox" />
          <span>이 기기에서 로그인 유지</span>
        </label>
        <label v-if="mode === 'register'" class="password-field">
          비밀번호 확인
          <input
            v-model="passwordConfirm"
            :type="showPassword ? 'text' : 'password'"
            autocomplete="new-password"
            minlength="12"
            maxlength="100"
            required
          />
        </label>
        <label v-if="mode === 'register'" class="auth-consent">
          <input v-model="acceptedTerms" type="checkbox" required />
          <span>
            <RouterLink to="/terms" target="_blank">이용약관</RouterLink>과
            <RouterLink to="/privacy" target="_blank">개인정보 처리 안내</RouterLink>를 확인했고 동의합니다.
          </span>
        </label>

        <p v-if="error" class="form-error" role="alert">{{ error }}</p>
        <p v-if="notice" class="form-success" role="status">{{ notice }}</p>

        <button class="press-button press-button--primary auth-submit" :disabled="busy">
          {{ busy ? "확인 중…" : mode === "login" ? "로그인" : "계정 만들기" }}
          <ArrowRight :size="18" />
        </button>

        <button
          class="text-button"
          type="button"
          @click="switchMode"
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
