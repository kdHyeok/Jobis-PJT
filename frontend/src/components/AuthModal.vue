<script setup lang="ts">
import { ArrowRight, X } from "@lucide/vue";
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api } from "@/api";
import logoWordmark from "@/assets/logo-wordmark.png";
import { session } from "@/session";

type AuthMode = "login" | "register";

const props = defineProps<{ mode: AuthMode }>();
const emit = defineEmits<{
  close: [];
  modeChange: [mode: AuthMode];
}>();

const route = useRoute();
const router = useRouter();
const email = ref("");
const password = ref("");
const displayName = ref("");
const rememberMe = ref(false);
const termsAccepted = ref(false);
const privacyAccepted = ref(false);
const busy = ref(false);
const error = ref(
  route.query.expired === "1"
    ? "로그인 시간이 만료되었습니다. 다시 로그인해 주세요."
    : "",
);

watch(
  () => props.mode,
  () => {
    error.value = "";
    termsAccepted.value = false;
    privacyAccepted.value = false;
  },
);

const title = computed(() =>
  props.mode === "login" ? "다시 이어서 가볼까요?" : "나만의 커리어 지도를 시작해요",
);

async function submit() {
  error.value = "";
  if (props.mode === "register" && (!termsAccepted.value || !privacyAccepted.value)) {
    error.value = "이용약관과 개인정보 처리 안내에 모두 동의해 주세요.";
    return;
  }
  busy.value = true;
  try {
    const user =
      props.mode === "login"
        ? await api.login(email.value, password.value, rememberMe.value)
        : await api.register(
            email.value,
            password.value,
            displayName.value,
            termsAccepted.value,
            privacyAccepted.value,
          );
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

function toggleMode() {
  emit("modeChange", props.mode === "login" ? "register" : "login");
}
</script>

<template>
  <Teleport to="body">
    <div class="landing-auth-overlay" @mousedown.self="emit('close')">
      <section
        v-dialog-focus
        class="landing-auth-dialog"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="`auth-modal-${mode}-title`"
        @keydown.esc.prevent="emit('close')"
      >
        <form class="auth-card" @submit.prevent="submit">
          <header class="auth-card__top">
            <img class="auth-card__brand" :src="logoWordmark" alt="JOBISS" draggable="false" />
            <button class="icon-button auth-card__close" type="button" aria-label="닫기" @click="emit('close')">
              <X :size="19" />
            </button>
          </header>

          <div class="auth-card__heading">
            <p class="eyebrow">{{ mode === "login" ? "WELCOME BACK" : "START JOURNEY" }}</p>
            <h2 :id="`auth-modal-${mode}-title`">{{ title }}</h2>
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

          <label v-if="mode === 'login'" class="auth-remember">
            <input v-model="rememberMe" type="checkbox" />
            <span>이 기기에서 로그인 유지</span>
          </label>

          <div v-if="mode === 'register'" class="auth-consents">
            <label class="auth-consent">
              <input v-model="termsAccepted" type="checkbox" required />
              <span>
                <a href="/terms" target="_blank" rel="noopener noreferrer">이용약관</a>에 동의합니다.
              </span>
            </label>
            <label class="auth-consent">
              <input v-model="privacyAccepted" type="checkbox" required />
              <span>
                <a href="/privacy" target="_blank" rel="noopener noreferrer">개인정보 처리 안내</a>에 동의합니다.
              </span>
            </label>
          </div>

          <p v-if="error" class="form-error" role="alert">{{ error }}</p>

          <button
            class="press-button press-button--primary auth-submit"
            :disabled="busy || (mode === 'register' && (!termsAccepted || !privacyAccepted))"
          >
            {{ busy ? "확인 중…" : mode === "login" ? "로그인" : "계정 만들기" }}
            <ArrowRight :size="18" />
          </button>

          <button class="text-button" type="button" @click="toggleMode">
            {{
              mode === "login"
                ? "처음인가요? 계정 만들기"
                : "이미 계정이 있나요? 로그인"
            }}
          </button>
        </form>
      </section>
    </div>
  </Teleport>
</template>
